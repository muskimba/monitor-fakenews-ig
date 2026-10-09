"""A planilha Google (um único arquivo, uma aba por tabela): é o banco e a interface.

A NOTÍCIA (a fake news em si) é a entidade central. Várias postagens, de vários perfis,
propagam a mesma notícia; desmentido e respostas pertencem à notícia e valem para todas.

  perfis [id] ──1:N──► postagens [shortcode]
                             │ 1:N
                             ▼
                       ocorrencias [shortcode:noticia_id]
                             │ N:1
                             ▼
                       noticias [id] ──1:1──► desmentidos [noticia_id]
                                     ──1:N──► respostas [id] (noticia_id)

Colunas de validação humana (lista suspensa): noticias, postagens, ocorrencias e respostas.
"""
import os
from collections import defaultdict
from datetime import datetime, timezone

import google.auth
import gspread
from google.auth import impersonated_credentials
from gspread.utils import ValidationConditionType, rowcol_to_a1

ESCOPOS = [
    "https://www.googleapis.com/auth/spreadsheets",
    "https://www.googleapis.com/auth/drive.readonly",
]

VALIDACAO = ["validacao_humana", "validado_por", "validado_em", "obs_validacao"]
RESUMO_NOTICIA = ["qtd_postagens", "qtd_perfis", "perfis", "primeira_postagem_em", "ultima_postagem_em"]

# Abas na ordem em que aparecem na planilha.
ESTRUTURA = {
    "perfis": [
        "id", "perfil", "nome", "link_perfil", "ativo", "observacao", "adicionado_em",
        "ultima_coleta", "status_ultima_coleta",
    ],
    "noticias": [
        "id", "titulo", "alegacao", "palavras_chave", *RESUMO_NOTICIA, *VALIDACAO, "criado_por", "criado_em",
    ],
    "postagens": [
        "shortcode", "link", "perfil_id", "perfil", "publicado_em", "tipo", "legenda",
        "relevante_campanha", "posicionamento", "depreciativo", "intensidade", "alvos", "tom", "justificativa",
        "alegacoes", "qtd_noticias", *VALIDACAO, "analisado_em", "modelo", "erro",
    ],
    "ocorrencias": [
        "id", "noticia_id", "titulo_noticia", "shortcode", "link_postagem", "perfil_id", "perfil",
        "publicado_em", "alegacao_na_postagem", "confianca", "resposta_usada_id", *VALIDACAO, "criado_em",
    ],
    "desmentidos": ["noticia_id", "titulo_noticia", "veredito", "explicacao", "fontes", "criado_em"],
    "respostas": ["id", "noticia_id", "tipo", "texto", "origem", *VALIDACAO, "criado_em"],
}

# Opções da lista suspensa de validação humana, por aba. O 1º valor é o que o robô grava.
OPCOES_VALIDACAO = {
    "noticias": ["pendente", "fake_confirmada", "parcialmente_falsa", "nao_e_fake", "inconclusiva", "duplicada"],
    "postagens": ["pendente", "analise_correta", "analise_incorreta"],
    "ocorrencias": ["pendente", "confirmada", "descartada", "respondida"],
    "respostas": ["pendente", "aprovada", "reprovada"],
}

VERDADEIRO = {"sim", "s", "true", "verdadeiro", "1", "x", "ativo"}
LIMITE_CELULA = 45000  # Sheets aceita até 50.000 caracteres por célula


def agora_iso() -> str:
    return datetime.now(timezone.utc).astimezone().isoformat(timespec="seconds")


def sim(valor) -> bool:
    return str(valor).strip().lower() in VERDADEIRO


def validacao(registro: dict) -> str:
    return str(registro.get("validacao_humana", "")).strip().lower()


def proximo_id(ids, prefixo: str, largura: int) -> str:
    numeros = [int(i[len(prefixo):]) for i in map(str, ids) if i.startswith(prefixo) and i[len(prefixo):].isdigit()]
    return f"{prefixo}{max(numeros, default=0) + 1:0{largura}d}"


def resumir_ocorrencias(ocorrencias: list[dict]) -> dict[str, dict]:
    """Por notícia: quantas postagens, quantos/quais perfis, primeira e última data (ignora descartadas)."""
    grupos = defaultdict(list)
    for o in ocorrencias:
        if o.get("noticia_id") and validacao(o) != "descartada":
            grupos[str(o["noticia_id"])].append(o)
    resumo = {}
    for nid, os_ in grupos.items():
        datas = sorted(str(o.get("publicado_em", "")) for o in os_ if o.get("publicado_em"))
        perfis = sorted({f"@{o['perfil']}" for o in os_ if o.get("perfil")})
        resumo[nid] = {
            "qtd_postagens": len({o["shortcode"] for o in os_}),
            "qtd_perfis": len(perfis),
            "perfis": ", ".join(perfis),
            "primeira_postagem_em": datas[0] if datas else "",
            "ultima_postagem_em": datas[-1] if datas else "",
        }
    return resumo


def credenciais_google():
    """Com GOOGLE_IMPERSONATE_SA: seu login do gcloud gera um token temporário da service account
    (sem arquivo de chave). Sem ela: credencial padrão (ex.: GOOGLE_APPLICATION_CREDENTIALS)."""
    sa = os.environ.get("GOOGLE_IMPERSONATE_SA", "").strip()
    if not sa:
        return google.auth.default(scopes=ESCOPOS)[0]
    origem, _ = google.auth.default(scopes=["https://www.googleapis.com/auth/cloud-platform"])
    projeto = sa.split("@")[1].split(".")[0]
    if hasattr(origem, "with_quota_project"):
        origem = origem.with_quota_project(projeto)
    return impersonated_credentials.Credentials(source_credentials=origem, target_principal=sa, target_scopes=ESCOPOS)


class Planilha:
    def __init__(self, planilha_id: str):
        self.planilha = gspread.authorize(credenciais_google()).open_by_key(planilha_id)

    def aba(self, nome: str) -> gspread.Worksheet:
        return self.planilha.worksheet(nome)

    def inicializar(self) -> None:
        existentes = {ws.title: ws for ws in self.planilha.worksheets()}
        for nome, colunas in ESTRUTURA.items():
            ws = existentes.get(nome) or self.planilha.add_worksheet(nome, rows=1000, cols=len(colunas))
            if not ws.row_values(1):
                ws.update([colunas], "A1", value_input_option="RAW")
                ws.freeze(rows=1)
            # Textos longos (legendas) não esticam a linha; o conteúdo completo aparece ao clicar.
            ws.format("A:Z", {"wrapStrategy": "CLIP", "verticalAlignment": "TOP"})
            if nome in OPCOES_VALIDACAO:
                _lista_suspensa(ws, colunas.index("validacao_humana") + 1, OPCOES_VALIDACAO[nome])
            if nome == "perfis":
                _lista_suspensa(ws, colunas.index("ativo") + 1, ["sim", "nao"])
        # Remove a aba padrão vazia ("Página1"/"Sheet1") criada junto com a planilha.
        for titulo, ws in existentes.items():
            if titulo in ("Página1", "Sheet1") and not any(any(linha) for linha in ws.get_all_values()):
                self.planilha.del_worksheet(ws)
        # Abas na ordem do ESTRUTURA.
        abas = {ws.title: ws for ws in self.planilha.worksheets()}
        self.planilha.reorder_worksheets([abas[n] for n in ESTRUTURA] + [w for t, w in abas.items() if t not in ESTRUTURA])

    # --- perfis ---------------------------------------------------------------

    def perfis_ativos(self) -> list[dict]:
        """Perfis com ativo=sim. Preenche o id (P001, P002…) de quem ainda não tem."""
        ws = self.aba("perfis")
        colunas = ESTRUTURA["perfis"]
        registros = ws.get_all_records()
        ids = [r.get("id", "") for r in registros]
        ativos, atualizacoes = [], []
        for linha, r in enumerate(registros, start=2):
            nome = str(r.get("perfil", "")).strip().lstrip("@")
            if not nome:
                continue
            if not str(r.get("id", "")).strip():
                r["id"] = proximo_id(ids, "P", 3)
                ids.append(r["id"])
                atualizacoes += _celulas(colunas, linha, {
                    "id": r["id"], "link_perfil": f"https://www.instagram.com/{nome}/", "adicionado_em": agora_iso(),
                })
            if sim(r.get("ativo", "")):
                ativos.append({"id": str(r["id"]), "perfil": nome, "linha": linha})
        if atualizacoes:
            ws.batch_update(atualizacoes, value_input_option="RAW")
        return ativos

    def registrar_coleta(self, linha: int, status: str) -> None:
        self.aba("perfis").batch_update(
            _celulas(ESTRUTURA["perfis"], linha, {"ultima_coleta": agora_iso(), "status_ultima_coleta": status[:500]}),
            value_input_option="RAW",
        )

    # --- noticias / postagens / ocorrencias -----------------------------------

    def noticias(self) -> list[dict]:
        return [{**n, "id": str(n["id"])} for n in self.aba("noticias").get_all_records()
                if str(n.get("id", "")).strip()]

    def shortcodes_existentes(self) -> set[str]:
        return {s for s in self.aba("postagens").col_values(1)[1:] if s}

    def ocorrencias(self) -> list[dict]:
        return self.aba("ocorrencias").get_all_records()

    def adicionar(self, aba: str, linhas: list[dict]) -> None:
        if linhas:
            # RAW: textos começando com "=" não viram fórmula.
            self.aba(aba).append_rows(
                [[_celula(l.get(c, "")) for c in ESTRUTURA[aba]] for l in linhas], value_input_option="RAW"
            )

    def atualizar_resumo_noticias(self) -> None:
        """Recalcula qtd_postagens, qtd_perfis, perfis e datas de todas as notícias (um único update)."""
        ws = self.aba("noticias")
        registros = ws.get_all_records()
        if not registros:
            return
        resumo = resumir_ocorrencias(self.ocorrencias())
        vazio = dict.fromkeys(RESUMO_NOTICIA, "")
        valores = [[resumo.get(str(n.get("id", "")), vazio)[c] for c in RESUMO_NOTICIA] for n in registros]
        colunas = ESTRUTURA["noticias"]
        ini = rowcol_to_a1(2, colunas.index(RESUMO_NOTICIA[0]) + 1)
        fim = rowcol_to_a1(len(registros) + 1, colunas.index(RESUMO_NOTICIA[-1]) + 1)
        ws.update(valores, f"{ini}:{fim}", value_input_option="RAW")

    def mesclar_noticias(self, origem: str, destino: str) -> str:
        """Move ocorrências, respostas e (se o destino não tiver) o desmentido de `origem` para `destino`."""
        noticias = {n["id"]: (linha, n) for linha, n in enumerate(self.noticias(), start=2)}
        if origem not in noticias or destino not in noticias or origem == destino:
            raise ValueError(f"Notícias inválidas para mescla: {origem} -> {destino}")
        titulo_destino = noticias[destino][1].get("titulo", "")

        ws_oc = self.aba("ocorrencias")
        col_oc = ESTRUTURA["ocorrencias"]
        ocorrencias = ws_oc.get_all_records()
        ja_no_destino = {o["shortcode"] for o in ocorrencias if str(o.get("noticia_id")) == destino}
        upd, movidas = [], 0
        for linha, o in enumerate(ocorrencias, start=2):
            if str(o.get("noticia_id")) != origem:
                continue
            campos = {"id": f"{o['shortcode']}:{destino}", "noticia_id": destino, "titulo_noticia": titulo_destino}
            if o["shortcode"] in ja_no_destino:
                campos.update(validacao_humana="descartada", obs_validacao=f"duplicada após mescla {origem}->{destino}")
            upd += _celulas(col_oc, linha, campos)
            movidas += 1
        if upd:
            ws_oc.batch_update(upd, value_input_option="RAW")

        ws_resp = self.aba("respostas")
        col_resp = ESTRUTURA["respostas"]
        upd = [c for linha, r in enumerate(ws_resp.get_all_records(), start=2) if str(r.get("noticia_id")) == origem
               for c in _celulas(col_resp, linha, {"noticia_id": destino})]
        if upd:
            ws_resp.batch_update(upd, value_input_option="RAW")

        ws_des = self.aba("desmentidos")
        col_des = ESTRUTURA["desmentidos"]
        desmentidos = ws_des.get_all_records()
        aviso = ""
        if not any(str(d.get("noticia_id")) == destino for d in desmentidos):
            upd = [c for linha, d in enumerate(desmentidos, start=2) if str(d.get("noticia_id")) == origem
                   for c in _celulas(col_des, linha, {"noticia_id": destino, "titulo_noticia": titulo_destino})]
            if upd:
                ws_des.batch_update(upd, value_input_option="RAW")
        elif any(str(d.get("noticia_id")) == origem for d in desmentidos):
            aviso = f" Atenção: {origem} e {destino} têm desmentido; o de {origem} ficou para você revisar."

        self.aba("noticias").batch_update(
            _celulas(ESTRUTURA["noticias"], noticias[origem][0],
                     {"validacao_humana": "duplicada", "obs_validacao": f"mesclada em {destino}"}),
            value_input_option="RAW",
        )
        self.atualizar_resumo_noticias()
        return f"{movidas} ocorrências movidas de {origem} para {destino}.{aviso}"

    # --- desmentidos / respostas ----------------------------------------------

    def desmentidos_por_noticia(self) -> dict[str, dict]:
        return {str(d["noticia_id"]): d for d in self.aba("desmentidos").get_all_records()
                if str(d.get("noticia_id", "")).strip()}

    def respostas(self) -> list[dict]:
        return [{**r, "id": str(r["id"])} for r in self.aba("respostas").get_all_records()
                if str(r.get("id", "")).strip()]


def _celulas(colunas: list[str], linha: int, campos: dict) -> list[dict]:
    return [{"range": rowcol_to_a1(linha, colunas.index(c) + 1), "values": [[_celula(v)]]} for c, v in campos.items()]


def _lista_suspensa(ws: gspread.Worksheet, coluna: int, opcoes: list[str]) -> None:
    letra = rowcol_to_a1(1, coluna).rstrip("1")
    ws.add_validation(f"{letra}2:{letra}", ValidationConditionType.one_of_list, opcoes,
                      strict=True, showCustomUi=True)


def _celula(valor) -> str | int | bool:
    if isinstance(valor, list):
        valor = "\n".join(str(v) for v in valor)
    if isinstance(valor, (int, bool)):
        return valor
    return str(valor)[:LIMITE_CELULA]
