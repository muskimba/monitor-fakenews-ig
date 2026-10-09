"""Teste de ponta a ponta de um perfil SEM as planilhas: coleta, analisa e salva em JSON local."""
import json
import logging
import os
from pathlib import Path

from dotenv import load_dotenv

from .instagram import ColetorInstagram, baixar_imagem

log = logging.getLogger(__name__)

PASTA_SAIDA = Path("saida")


def testar_perfil(perfil: str, limite: int, analisar: bool) -> Path:
    load_dotenv()
    perfil = perfil.strip().rstrip("/").split("/")[-1].lstrip("@")  # aceita URL, @perfil ou perfil
    usuario = os.environ.get("IG_USER", "").strip() or None
    sessao = os.environ.get("IG_SESSION_FILE", "").strip() or None
    log.info("Coletando até %d posts de @%s (%s).", limite, perfil,
             f"sessão de @{usuario}" if usuario else "SEM login")
    publicacoes = ColetorInstagram(usuario, sessao).publicacoes_novas(perfil, limite, set())
    log.info("%d posts coletados.", len(publicacoes))

    analisador = None
    if analisar:
        if os.environ.get("ANTHROPIC_API_KEY"):
            from .analise import Analisador
            analisador = Analisador(os.environ.get("CLAUDE_MODEL", "claude-opus-5-5"),
                                    os.environ.get("CLAUDE_EFFORT", "medium"))
        else:
            log.warning("ANTHROPIC_API_KEY não definida: só a coleta será testada.")

    catalogo, resultados = [], []
    for pub in publicacoes:
        item = {"link": pub.link, "publicado_em": pub.publicado_em.isoformat() + "Z", "tipo": pub.tipo,
                "legenda": pub.legenda, "imagem_url": pub.imagem_url}
        if analisador:
            r = analisador.analisar(pub.perfil, pub.link, item["publicado_em"], pub.legenda,
                                    baixar_imagem(pub.imagem_url), catalogo)
            # catálogo em memória, para ver o agrupamento entre posts do teste
            for o in r["noticias"]:
                if not o["noticia_id"]:
                    o["noticia_id"] = f"N{len(catalogo) + 1:04d}"
                    catalogo.append({"id": o["noticia_id"], "titulo": o["titulo_nova"],
                                     "alegacao": o["alegacao_nova"], "palavras_chave": o["palavras_chave_nova"]})
            item["analise"] = r
        resultados.append(item)
        print(f"\n{pub.link}  ({pub.publicado_em:%d/%m %H:%M})\n  {pub.legenda[:160]!r}")
        if "analise" in item:
            a = item["analise"]
            print(f"  campanha: relevante={a['relevante_campanha']}, {a['posicionamento']}, "
                  f"depreciativo={a['depreciativo']} ({a['intensidade']}), tom={a['tom']}; alvos={a['alvos']}")
            for o in a["noticias"]:
                print(f"  notícia {o['noticia_id']}: {o['alegacao_na_postagem']}")

    PASTA_SAIDA.mkdir(exist_ok=True)
    arquivo = PASTA_SAIDA / f"teste-{perfil}.json"
    arquivo.write_text(json.dumps({"perfil": perfil, "catalogo": catalogo, "posts": resultados},
                                  ensure_ascii=False, indent=2), encoding="utf-8")
    return arquivo
