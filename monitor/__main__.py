import argparse
import json
import logging
import os
import sys

from instaloader.exceptions import InstaloaderException

from . import config, pipeline
from .analise import Analisador
from .instagram import SessaoInvalida


def main() -> None:
    parser = argparse.ArgumentParser(prog="python -m monitor")
    sub = parser.add_subparsers(dest="comando", required=True)
    sub.add_parser("init-planilha", help="cria as abas, cabeçalhos e listas de validação na planilha")
    sub.add_parser("coletar", help="coleta postagens novas, analisa e liga cada uma às notícias (o que o agendador roda)")
    sub.add_parser("gerar-respostas", help="rascunha respostas para notícias falsas confirmadas que têm desmentido")
    sub.add_parser("verificar-integridade", help="aponta chaves repetidas, vazias ou que apontam para registro inexistente")
    mesclar = sub.add_parser("mesclar-noticias", help="junta uma notícia duplicada (ORIGEM) em outra (DESTINO)")
    mesclar.add_argument("origem")
    mesclar.add_argument("destino")
    tp = sub.add_parser("testar-perfil", help="coleta e analisa um perfil sem usar as planilhas (salva em saida/)")
    tp.add_argument("perfil", help="nome, @nome ou URL do perfil")
    tp.add_argument("--limite", type=int, default=3)
    tp.add_argument("--sem-claude", action="store_true", help="só testa a coleta")
    teste = sub.add_parser("testar-analise", help="testa a análise com uma legenda, sem Instagram")
    teste.add_argument("legenda")
    args = parser.parse_args()

    logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(name)s: %(message)s")

    if args.comando == "coletar":
        try:
            pipeline.coletar(config.carregar())
        except SessaoInvalida as e:
            logging.critical("Sessão do Instagram inválida: %s", e)
            sys.exit(2)
        return

    if args.comando == "testar-perfil":
        from .teste_perfil import testar_perfil
        try:
            arquivo = testar_perfil(args.perfil, args.limite, analisar=not args.sem_claude)
        except SessaoInvalida as e:
            logging.critical("Sessão do Instagram inválida: %s", e)
            sys.exit(2)
        except InstaloaderException as e:
            logging.critical("Instagram recusou a coleta: %s", e)
            if not os.environ.get("IG_USER"):
                logging.critical("Sem login o Instagram quase sempre bloqueia. Crie a sessão com "
                                 "`.venv\\Scripts\\instaloader -l USUARIO` e preencha IG_USER no .env.")
            sys.exit(3)
        print(f"\nResultado salvo em {arquivo}")
        return

    cfg = config.carregar(precisa_instagram=False)
    if args.comando == "init-planilha":
        pipeline._planilha(cfg).inicializar()
        print("Planilha pronta: abas perfis, noticias, postagens, ocorrencias, desmentidos e respostas.")
    elif args.comando == "mesclar-noticias":
        print(pipeline._planilha(cfg).mesclar_noticias(args.origem.upper(), args.destino.upper()))
    elif args.comando == "gerar-respostas":
        pipeline.gerar_respostas(cfg)
    elif args.comando == "verificar-integridade":
        problemas = pipeline._planilha(cfg).verificar_integridade()
        print("\n".join(problemas) if problemas else "Integridade OK: todas as chaves batem.")
        sys.exit(1 if problemas else 0)
    elif args.comando == "testar-analise":
        noticias = pipeline._planilha(cfg).noticias()
        resultado = Analisador(cfg.modelo, cfg.esforco).analisar(
            "teste", "https://www.instagram.com/p/teste/", "agora", args.legenda, None, noticias
        )
        print(json.dumps(resultado, ensure_ascii=False, indent=2))


if __name__ == "__main__":
    main()
