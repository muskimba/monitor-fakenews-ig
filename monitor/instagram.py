"""Coleta de publicações via instaloader, usando uma sessão já logada.

A sessão é criada uma única vez, na sua máquina, com `instaloader -l USUARIO`
(você digita a senha). Use uma conta secundária: o Instagram pode bloquear
contas que fazem coleta automatizada.
"""
import logging
from dataclasses import dataclass
from datetime import datetime

import instaloader
import requests
from instaloader.exceptions import (
    BadCredentialsException,
    LoginRequiredException,
    QueryReturnedForbiddenException,
    TwoFactorAuthRequiredException,
)

log = logging.getLogger(__name__)

TIPOS_IMAGEM_ACEITOS = {"image/jpeg", "image/png", "image/webp", "image/gif"}
LIMITE_IMAGEM_BYTES = 5 * 1024 * 1024


class SessaoInvalida(RuntimeError):
    """Sessão do Instagram expirou ou foi bloqueada: é preciso gerar outra."""


@dataclass
class Publicacao:
    shortcode: str
    perfil: str
    publicado_em: datetime
    legenda: str
    tipo: str
    imagem_url: str | None

    @property
    def link(self) -> str:
        return f"https://www.instagram.com/p/{self.shortcode}/"


class ColetorInstagram:
    def __init__(self, usuario: str | None, arquivo_sessao: str | None):
        """Sem `usuario`, acessa sem login (só para testes: o Instagram limita muito o acesso anônimo)."""
        self.loader = instaloader.Instaloader(
            download_pictures=False,
            download_videos=False,
            download_video_thumbnails=False,
            download_geotags=False,
            download_comments=False,
            save_metadata=False,
            quiet=True,
            max_connection_attempts=1,
        )
        if not usuario:
            return
        try:
            self.loader.load_session_from_file(usuario, arquivo_sessao)
        except FileNotFoundError as e:
            raise SessaoInvalida(
                f"Arquivo de sessão não encontrado ({arquivo_sessao or 'local padrão'}); rode `instaloader -l {usuario}`."
            ) from e
        if self.loader.test_login() is None:
            raise SessaoInvalida("Sessão do Instagram expirada ou bloqueada; gere outra com `instaloader -l`.")

    def publicacoes_novas(self, perfil: str, limite: int, conhecidos: set[str]) -> list[Publicacao]:
        """Retorna as publicações mais recentes do perfil que ainda não estão na planilha.

        Olha no máximo `limite` posts (posts fixados aparecem primeiro, por isso
        não paramos no primeiro já conhecido).
        """
        try:
            profile = instaloader.Profile.from_username(self.loader.context, perfil)
            novas = []
            for i, post in enumerate(profile.get_posts()):
                if i >= limite:
                    break
                if post.shortcode in conhecidos:
                    continue
                novas.append(
                    Publicacao(
                        shortcode=post.shortcode,
                        perfil=perfil,
                        publicado_em=post.date_utc,
                        legenda=post.caption or "",
                        tipo=post.typename,
                        imagem_url=post.url,  # 1ª imagem do carrossel ou capa do vídeo
                    )
                )
            return novas
        except (LoginRequiredException, BadCredentialsException, TwoFactorAuthRequiredException,
                QueryReturnedForbiddenException) as e:
            raise SessaoInvalida(str(e)) from e


def baixar_imagem(url: str | None) -> tuple[bytes, str] | None:
    """Baixa a imagem do post para mandar ao Claude. Falha silenciosa: segue só com a legenda."""
    if not url:
        return None
    try:
        r = requests.get(url, timeout=30)
        r.raise_for_status()
    except requests.RequestException as e:
        log.warning("Não consegui baixar a imagem (%s); analisando só a legenda.", e)
        return None
    tipo = r.headers.get("Content-Type", "").split(";")[0].strip()
    if tipo not in TIPOS_IMAGEM_ACEITOS or len(r.content) > LIMITE_IMAGEM_BYTES:
        log.warning("Imagem ignorada (tipo=%s, %d bytes).", tipo, len(r.content))
        return None
    return r.content, tipo
