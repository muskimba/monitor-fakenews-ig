import logging
import random
import time

import anthropic
from instaloader.exceptions import InstaloaderException

from .analise import Analisador, AnaliseRecusada
from .config import Config
from .instagram import ColetorInstagram, Publicacao, baixar_imagem
from .planilha import Planilha, agora_iso, proximo_id, validacao

log = logging.getLogger(__name__)

# Notícias nesses estados recebem rascunho de respostas no `gerar-respostas`.
NOTICIA_A_RESPONDER = {"fake_confirmada", "parcialmente_falsa"}


def _planilha(cfg: Config) -> Planilha:
    return Planilha(cfg.planilha_id)


def coletar(cfg: Config) -> None:
    planilha = _planilha(cfg)
    perfis = planilha.perfis_ativos()
    if not perfis:
        log.warning("Nenhum perfil ativo na aba perfis.")
        return
    conhecidos = planilha.shortcodes_existentes()
    catalogo = planilha.noticias()  # cresce durante a execução: a 2ª postagem já casa com a notícia criada pela 1ª
    coletor = ColetorInstagram(cfg.ig_user, cfg.ig_session_file)  # SessaoInvalida aborta a execução
    analisador = Analisador(cfg.modelo, cfg.esforco)
    log.info("Monitorando %d perfis; %d postagens já registradas; %d notícias no catálogo.",
             len(perfis), len(conhecidos), len(catalogo))

    total = 0
    for i, p in enumerate(perfis):
        perfil = p["perfil"]
        if i:
            time.sleep(cfg.pausa_entre_perfis_s + random.uniform(0, cfg.pausa_entre_perfis_s))
        try:
            novas = coletor.publicacoes_novas(perfil, cfg.max_posts_por_perfil, conhecidos)
        except InstaloaderException as e:
            log.error("@%s: falha na coleta (%s); seguindo para o próximo perfil.", perfil, e)
            planilha.registrar_coleta(p["linha"], f"erro: {e}")
            continue

        lote = {"noticias": [], "postagens": [], "ocorrencias": []}
        for pub in sorted(novas, key=lambda x: x.publicado_em):
            resultado = processar_postagem(pub, p["id"], analisador, cfg, catalogo)
            if resultado is None:
                continue
            for aba, linhas in resultado.items():
                lote[aba].extend(linhas)
            conhecidos.add(pub.shortcode)
        # Grava por perfil (notícias antes, para as ocorrências já apontarem para algo que existe).
        for aba in ("noticias", "postagens", "ocorrencias"):
            planilha.adicionar(aba, lote[aba])
        planilha.registrar_coleta(p["linha"], f"ok: {len(lote['postagens'])} novas")
        total += len(lote["postagens"])
        log.info("@%s: %d postagens, %d ocorrências, %d notícias novas.",
                 perfil, len(lote["postagens"]), len(lote["ocorrencias"]), len(lote["noticias"]))

    planilha.atualizar_resumo_noticias()
    log.info("Fim: %d postagens registradas nesta execução.", total)
    avisar_integridade(planilha)


def avisar_integridade(planilha: Planilha) -> list[str]:
    """Edições manuais (ex.: apagar uma notícia) podem deixar chaves órfãs; avisa no log."""
    problemas = planilha.verificar_integridade()
    if problemas:
        log.warning("Integridade: %d problema(s) na planilha (rode `verificar-integridade`): %s",
                    len(problemas), "; ".join(problemas[:5]) + (" …" if len(problemas) > 5 else ""))
    return problemas


def processar_postagem(pub: Publicacao, perfil_id: str, analisador: Analisador, cfg: Config,
                       catalogo: list[dict]) -> dict[str, list[dict]] | None:
    """Analisa uma postagem e devolve as linhas a gravar. Notícias novas são acrescentadas ao `catalogo`."""
    postagem = {
        "shortcode": pub.shortcode,
        "link": pub.link,
        "perfil_id": perfil_id,
        "perfil": pub.perfil,
        "publicado_em": pub.publicado_em.isoformat(timespec="seconds") + "Z",
        "tipo": pub.tipo,
        "legenda": pub.legenda,
        "validacao_humana": "pendente",
        "analisado_em": agora_iso(),
        "modelo": cfg.modelo,
    }
    try:
        resultado = analisador.analisar(
            pub.perfil, pub.link, postagem["publicado_em"], pub.legenda, baixar_imagem(pub.imagem_url), catalogo
        )
    except AnaliseRecusada as e:
        return {"noticias": [], "postagens": [{**postagem, "erro": str(e)}], "ocorrencias": []}
    except anthropic.APIError as e:
        # Erro transitório (rede, 429, 5xx): não grava, para tentar de novo na próxima execução.
        log.error("%s: erro na API do Claude (%s); fica para a próxima execução.", pub.link, e)
        return None

    novas_noticias, ocorrencias = [], []
    titulos = {n["id"]: n.get("titulo", "") for n in catalogo}
    for o in resultado.pop("noticias"):
        noticia_id = o["noticia_id"]
        if not noticia_id:
            noticia_id = proximo_id(titulos, "N", 4)
            nova = {
                "id": noticia_id, "titulo": o["titulo_nova"], "alegacao": o["alegacao_nova"],
                "palavras_chave": o["palavras_chave_nova"], "validacao_humana": "pendente",
                "criado_por": "claude", "criado_em": agora_iso(),
            }
            novas_noticias.append(nova)
            catalogo.append(nova)
            titulos[noticia_id] = nova["titulo"]
        ocorrencias.append({
            "id": f"{pub.shortcode}:{noticia_id}",
            "noticia_id": noticia_id,
            "titulo_noticia": titulos[noticia_id],
            "shortcode": pub.shortcode,
            "link_postagem": pub.link,
            "perfil_id": perfil_id,
            "perfil": pub.perfil,
            "publicado_em": postagem["publicado_em"],
            "alegacao_na_postagem": o["alegacao_na_postagem"],
            "confianca": o["confianca"],
            "validacao_humana": "pendente",
            "criado_em": agora_iso(),
        })
    postagem.update(resultado, qtd_noticias=len(ocorrencias))
    return {"noticias": novas_noticias, "postagens": [postagem], "ocorrencias": ocorrencias}


def gerar_respostas(cfg: Config) -> None:
    """Rascunha respostas para notícias confirmadas como falsas que têm desmentido e nenhuma resposta ativa."""
    planilha = _planilha(cfg)
    desmentidos = planilha.desmentidos_por_noticia()
    respostas = planilha.respostas()
    analisador = Analisador(cfg.modelo, cfg.esforco)
    total = 0
    for n in planilha.noticias():
        if validacao(n) not in NOTICIA_A_RESPONDER or n["id"] not in desmentidos:
            continue
        da_noticia = [r for r in respostas if str(r.get("noticia_id")) == n["id"]]
        # Se todas as existentes foram reprovadas, rascunha de novo.
        if any(validacao(r) != "reprovada" for r in da_noticia):
            continue
        try:
            novas = analisador.gerar_respostas(n, desmentidos[n["id"]])
        except (AnaliseRecusada, anthropic.APIError) as e:
            log.error("Notícia %s: %s", n["id"], e)
            continue
        ids = [r["id"] for r in respostas]
        linhas = []
        for r in novas:
            rid = proximo_id(ids, f"{n['id']}-R", 1)
            ids.append(rid)
            linhas.append({"id": rid, "noticia_id": n["id"], "tipo": r["tipo"], "texto": r["texto"],
                           "origem": "claude", "validacao_humana": "pendente", "criado_em": agora_iso()})
        planilha.adicionar("respostas", linhas)
        total += len(linhas)
        log.info("Notícia %s: %d respostas rascunhadas.", n["id"], len(linhas))
    log.info("Fim: %d respostas novas aguardando validação humana na aba 'respostas'.", total)
