import os
from dataclasses import dataclass

from dotenv import load_dotenv


@dataclass(frozen=True)
class Config:
    planilha_id: str
    ig_user: str
    ig_session_file: str | None
    modelo: str
    esforco: str
    max_posts_por_perfil: int
    pausa_entre_perfis_s: int


def _obrigatoria(nome: str) -> str:
    valor = os.environ.get(nome, "").strip()
    if not valor:
        raise SystemExit(f"Variável de ambiente obrigatória ausente: {nome} (veja .env.example)")
    return valor


def carregar(precisa_instagram: bool = True) -> Config:
    load_dotenv()
    return Config(
        planilha_id=_obrigatoria("PLANILHA_ID"),
        ig_user=_obrigatoria("IG_USER") if precisa_instagram else os.environ.get("IG_USER", ""),
        # Vazio = local padrão onde o `instaloader -l` salva a sessão.
        ig_session_file=os.environ.get("IG_SESSION_FILE", "").strip() or None,
        modelo=os.environ.get("CLAUDE_MODEL", "claude-opus-5-5"),
        esforco=os.environ.get("CLAUDE_EFFORT", "medium"),
        max_posts_por_perfil=int(os.environ.get("MAX_POSTS_POR_PERFIL", "12")),
        pausa_entre_perfis_s=int(os.environ.get("PAUSA_ENTRE_PERFIS_S", "20")),
    )
