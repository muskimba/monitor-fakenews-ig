import json
from datetime import datetime
from types import SimpleNamespace

from monitor import pipeline
from monitor.analise import SCHEMA_ANALISE, Analisador, formatar_catalogo
from monitor.config import Config
from monitor.instagram import Publicacao
from monitor.planilha import (
    ESTRUTURA, VALIDACAO, Planilha, _celula, proximo_id, resumir_ocorrencias,
)

CFG = Config("id", "u", None, "claude-opus-5-5", "medium", 12, 0)


class ClienteFalso:
    def __init__(self, *respostas):
        self.chamadas = []
        self._respostas = list(respostas)
        self.beta = SimpleNamespace(messages=SimpleNamespace(create=self._create))

    def _create(self, **kwargs):
        self.chamadas.append(kwargs)
        return self._respostas.pop(0)


def _resposta(dados, stop="end_turn"):
    return SimpleNamespace(stop_reason=stop, stop_details=None,
                           content=[SimpleNamespace(type="text", text=json.dumps(dados))])


def _ocorrencia(noticia_id="", titulo=""):
    return {"alegacao_na_postagem": "a", "noticia_id": noticia_id, "titulo_nova": titulo,
            "alegacao_nova": "alegação" if titulo else "", "palavras_chave_nova": "x" if titulo else "",
            "confianca": "alta"}


def _analise(*ocorrencias):
    return {"relevante_campanha": True, "posicionamento": "desfavoravel", "depreciativo": True,
            "intensidade": 2, "alvos": ["Lula"],
            "tom": "irônico", "justificativa": "x", "alegacoes": ["a"], "noticias": list(ocorrencias)}


CATALOGO = [
    {"id": "N0001", "titulo": "Vacina X causa Y", "alegacao": "...", "validacao_humana": "fake_confirmada"},
    {"id": "N0002", "titulo": "Duplicada", "alegacao": "...", "validacao_humana": "duplicada"},
]


def _pub(shortcode, perfil):
    return Publicacao(shortcode, perfil, datetime(2026, 10, 9, 12), "leg", "GraphImage", None)


def test_requisicao_e_validacao():
    resposta = _analise(_ocorrencia("N0001"), _ocorrencia("N0001"), _ocorrencia("N0002"),
                        _ocorrencia("N9999", "Nova narrativa"), _ocorrencia(""))
    cli = ClienteFalso(_resposta(resposta))
    r = Analisador("claude-opus-5-5", "medium", cli).analisar("p", "l", "d", "leg", (b"img", "image/jpeg"), CATALOGO)
    req = cli.chamadas[0]
    assert req["fallbacks"] == "default"
    assert req["output_config"]["format"]["schema"] is SCHEMA_ANALISE
    assert req["messages"][0]["content"][0]["type"] == "image"
    # repetida, duplicada e vazia saem; id inventado com título vira notícia nova
    assert [(o["noticia_id"], o["titulo_nova"]) for o in r["noticias"]] == [("N0001", ""), ("", "Nova narrativa")]


def test_contexto_da_campanha_vai_no_prompt():
    cli = ClienteFalso(_resposta(_analise()))
    Analisador("m", "low", cli, contexto="ALVOS: Lula, PT").analisar("p", "l", "d", "leg", None, [])
    assert "<contexto_campanha>\nALVOS: Lula, PT\n</contexto_campanha>" in cli.chamadas[0]["system"][0]["text"]


def test_contexto_padrao_existe_e_cita_alvos():
    from monitor.analise import carregar_contexto
    texto = carregar_contexto()
    assert "Lula" in texto and "PT" in texto and "elei" in texto


def test_nao_depreciativo_zera_intensidade_e_alvos():
    dados = {**_analise(), "depreciativo": False, "intensidade": 2, "alvos": ["Lula"]}
    r = Analisador("m", "low", ClienteFalso(_resposta(dados)), contexto="x").analisar("p", "l", "d", "leg", None, [])
    assert (r["intensidade"], r["alvos"]) == (0, [])


def test_catalogo_esconde_duplicadas():
    texto = formatar_catalogo(CATALOGO)
    assert "N0001" in texto and "N0002" not in texto


def test_dois_perfis_mesma_noticia():
    """A 1ª postagem cria a notícia; a 2ª, de outro perfil, aponta para a mesma."""
    catalogo = list(CATALOGO)
    cli = ClienteFalso(_resposta(_analise(_ocorrencia("", "Boato Z"))), _resposta(_analise(_ocorrencia("N0003"))))
    analisador = Analisador("m", "low", cli)
    r1 = pipeline.processar_postagem(_pub("AAA", "perfil_a"), "P001", analisador, CFG, catalogo)
    r2 = pipeline.processar_postagem(_pub("BBB", "perfil_b"), "P002", analisador, CFG, catalogo)
    assert [n["id"] for n in r1["noticias"]] == ["N0003"] and r2["noticias"] == []
    assert "N0003" in cli.chamadas[1]["system"][-1]["text"]  # catálogo da 2ª chamada já tem a notícia nova
    o1, o2 = r1["ocorrencias"][0], r2["ocorrencias"][0]
    assert (o1["id"], o1["perfil_id"]) == ("AAA:N0003", "P001")
    assert (o2["id"], o2["perfil_id"], o2["titulo_noticia"]) == ("BBB:N0003", "P002", "Boato Z")
    assert r1["postagens"][0]["qtd_noticias"] == 1 and r1["postagens"][0]["validacao_humana"] == "pendente"


def test_recusa_grava_postagem_com_erro():
    analisador = Analisador("m", "low", ClienteFalso(_resposta({}, stop="refusal")))
    r = pipeline.processar_postagem(_pub("CCC", "x"), "P001", analisador, CFG, [])
    assert "recusou" in r["postagens"][0]["erro"] and r["ocorrencias"] == []


def test_resumo_por_noticia():
    oc = [
        {"noticia_id": "N0001", "shortcode": "A", "perfil": "a", "publicado_em": "2026-10-02"},
        {"noticia_id": "N0001", "shortcode": "B", "perfil": "b", "publicado_em": "2026-10-01"},
        {"noticia_id": "N0001", "shortcode": "C", "perfil": "a", "publicado_em": "2026-10-05"},
        {"noticia_id": "N0001", "shortcode": "D", "perfil": "c", "publicado_em": "2026-10-09",
         "validacao_humana": "descartada"},
    ]
    assert resumir_ocorrencias(oc)["N0001"] == {
        "qtd_postagens": 3, "qtd_perfis": 2, "perfis": "@a, @b",
        "primeira_postagem_em": "2026-10-01", "ultima_postagem_em": "2026-10-05",
    }


def test_proximo_id():
    assert proximo_id([], "N", 4) == "N0001"
    assert proximo_id(["N0009", "N0002", "X"], "N", 4) == "N0010"
    assert proximo_id(["N0001-R1", "N0001-R2", "N0002-R1"], "N0001-R", 1) == "N0001-R3"


def test_uma_planilha_seis_abas():
    assert list(ESTRUTURA) == ["perfis", "noticias", "postagens", "ocorrencias", "desmentidos", "respostas"]


def test_colunas_de_validacao_e_chaves():
    for cols in (ESTRUTURA["noticias"], ESTRUTURA["postagens"],
                 ESTRUTURA["ocorrencias"], ESTRUTURA["respostas"]):
        assert all(c in cols for c in VALIDACAO)
    assert {"noticia_id", "shortcode", "perfil_id"} <= set(ESTRUTURA["ocorrencias"])
    assert ESTRUTURA["desmentidos"][0] == "noticia_id"
    assert "noticia_id" in ESTRUTURA["respostas"]


def test_celula_lista_e_formula():
    assert _celula(["a", "b"]) == "a\nb"
    assert _celula(True) is True
    assert _celula("=IMPORTXML()") == "=IMPORTXML()"  # gravado com RAW, não vira fórmula


class AbaFalsa:
    def __init__(self, registros):
        self.registros, self.updates = registros, []

    def get_all_records(self):
        return self.registros

    def batch_update(self, upd, value_input_option):
        self.updates += upd

    def update(self, valores, intervalo, value_input_option):
        self.updates.append({"range": intervalo, "values": valores})


def _planilha_falsa(**abas):
    pl = Planilha.__new__(Planilha)
    pl.planilha = SimpleNamespace(worksheet=lambda nome: abas[nome])
    return pl


def test_perfis_ativos_gera_ids_que_faltam():
    aba = AbaFalsa([
        {"id": "P002", "perfil": "@jornal_a", "ativo": "sim"},
        {"id": "", "perfil": "jornal_b", "ativo": "sim"},
        {"id": "", "perfil": "jornal_c", "ativo": "nao"},
        {"id": "", "perfil": "", "ativo": "sim"},
    ])
    ativos = _planilha_falsa(perfis=aba).perfis_ativos()
    assert [(a["id"], a["perfil"], a["linha"]) for a in ativos] == [("P002", "jornal_a", 2), ("P003", "jornal_b", 3)]
    assert [u["values"][0][0] for u in aba.updates if u["range"].startswith("A")] == ["P003", "P004"]


def test_mesclar_noticias():
    noticias = AbaFalsa([{"id": "N0001", "titulo": "Certa"}, {"id": "N0002", "titulo": "Dup"}])
    ocorrencias = AbaFalsa([
        {"id": "A:N0001", "noticia_id": "N0001", "shortcode": "A"},
        {"id": "A:N0002", "noticia_id": "N0002", "shortcode": "A"},  # mesma postagem nas duas
        {"id": "B:N0002", "noticia_id": "N0002", "shortcode": "B"},
    ])
    respostas = AbaFalsa([{"id": "N0002-R1", "noticia_id": "N0002"}])
    desmentidos = AbaFalsa([{"noticia_id": "N0002", "veredito": "falso"}])
    pl = _planilha_falsa(noticias=noticias, ocorrencias=ocorrencias, respostas=respostas, desmentidos=desmentidos)
    msg = pl.mesclar_noticias("N0002", "N0001")
    assert msg.startswith("2 ocorrências movidas")
    cel = {u["range"]: u["values"][0][0] for u in ocorrencias.updates}
    assert cel["A3"] == "A:N0001" and cel["L3"] == "descartada"  # duplicada na mesma postagem
    assert cel["A4"] == "B:N0001" and cel["B4"] == "N0001" and "L4" not in cel
    assert {"range": "B2", "values": [["N0001"]]} in respostas.updates
    assert {"range": "A2", "values": [["N0001"]]} in desmentidos.updates  # destino não tinha desmentido
    assert any(u["values"] == [["duplicada"]] for u in noticias.updates)


def test_respostas_nunca_tem_link():
    from monitor.analise import sem_links
    assert sem_links("Falso. Fonte: CNN Brasil (https://www.cnnbrasil.com.br/x/).") == "Falso. Fonte: CNN Brasil."
    assert sem_links("Veja mais em www.site.com.br e confira.") == "Veja mais em e confira."
    assert sem_links("Recusado pela PF. Detalhes: https://ac24horas.com/a/b") == "Recusado pela PF."
    assert sem_links("Segundo a Polícia Federal, não há prova.") == "Segundo a Polícia Federal, não há prova."


def test_gerar_respostas_remove_links_e_pede_citacao_sem_link():
    dados = {"respostas": [{"tipo": "completa", "texto": "Não comprovado, segundo a PF (https://pf.gov.br/nota)."}]}
    cli = ClienteFalso(_resposta(dados))
    r = Analisador("m", "low", cli, contexto="x").gerar_respostas({"titulo": "t"}, {"veredito": "nao_comprovado"})
    assert r[0]["texto"] == "Não comprovado, segundo a PF."
    assert "NUNCA coloque links" in cli.chamadas[0]["system"][0]["text"]
