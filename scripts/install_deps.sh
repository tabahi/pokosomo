#!/usr/bin/env bash
# Installs everything the studio and its agents need for research work:
#   - LaTeX (XeLaTeX/LuaLaTeX, science + bibliography packages) and pandoc for PDF/Word output
#   - Document tools: LibreOffice (headless), poppler, qpdf, OCR (tesseract/ocrmypdf), ImageMagick
#   - R for statistics, plus a broad scientific Python stack in the project venv
#
# Safe to re-run: apt/pip skip what is already installed.
# Usage:  ./scripts/install_deps.sh            (everything)
#         SKIP_APT=1 ./scripts/install_deps.sh (Python packages only)
set -euo pipefail

ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." >/dev/null 2>&1 && pwd)"
VENV="${POKOSOMO_VENV:-$ROOT/.venv}"
export PATH="$HOME/.local/bin:$PATH"
export DEBIAN_FRONTEND=noninteractive

log() { printf '\n\033[1;36m==> %s\033[0m\n' "$*"; }

SUDO=()
if [[ "${SKIP_APT:-0}" != "1" && "$EUID" -ne 0 ]]; then
  if ! command -v sudo >/dev/null 2>&1; then
    echo "Install sudo or run this script as root to install system packages." >&2
    exit 1
  fi
  SUDO=(sudo)
fi

if [[ "${SKIP_APT:-0}" != "1" ]]; then
  if ! command -v apt-get >/dev/null 2>&1; then
    echo "This installer currently supports Debian/Ubuntu systems with apt-get." >&2
    exit 1
  fi
  log "Installing system packages (LaTeX, pandoc, document & OCR tools, R)"
  "${SUDO[@]}" apt-get update -qq
  "${SUDO[@]}" apt-get install -y --no-install-recommends \
    python3 python3-venv python3-pip \
    pandoc \
    texlive-xetex texlive-luatex texlive-latex-base texlive-latex-recommended texlive-latex-extra \
    texlive-fonts-recommended texlive-fonts-extra texlive-science texlive-pictures \
    texlive-bibtex-extra texlive-publishers texlive-plain-generic texlive-lang-greek \
    biber latexmk lmodern fonts-texgyre fonts-dejavu fonts-noto-core fonts-liberation2 \
    poppler-utils qpdf ghostscript librsvg2-bin imagemagick \
    tesseract-ocr tesseract-ocr-eng ocrmypdf \
    libreoffice-writer-nogui libreoffice-calc-nogui libreoffice-impress-nogui \
    r-base-core r-recommended \
    zip unzip p7zip-full curl wget jq sqlite3 build-essential lsof nodejs npm sudo
  "${SUDO[@]}" apt-get clean

  log "Making TeX Live's OpenType fonts (Libertinus etc.) visible to XeLaTeX via fontconfig"
  "${SUDO[@]}" tee /etc/fonts/conf.d/09-texlive-opentype.conf >/dev/null <<'EOF'
<?xml version="1.0"?>
<!DOCTYPE fontconfig SYSTEM "fonts.dtd">
<fontconfig>
  <dir>/usr/share/texlive/texmf-dist/fonts/opentype</dir>
</fontconfig>
EOF
  "${SUDO[@]}" fc-cache -f >/dev/null

  log "Installing Claude Code and Codex command-line tools"
  "${SUDO[@]}" npm install --global @anthropic-ai/claude-code
  if ! command -v codex >/dev/null 2>&1 && [[ ! -x "$HOME/.local/bin/codex" ]]; then
    curl -fsSL https://chatgpt.com/codex/install.sh | sh
  fi
fi

if [[ ! -x "$VENV/bin/python" ]]; then
  log "Creating Python environment at $VENV"
  python3 -m venv "$VENV"
fi

log "Installing Python packages into $VENV"
PIP="$VENV/bin/pip"
"$PIP" install -q --upgrade pip
"$PIP" install -q -r "$ROOT/requirements.txt"
# Statistics & plotting
"$PIP" install -q --upgrade statsmodels seaborn pingouin scikit-posthocs lifelines plotly tabulate
# Spreadsheets & documents
"$PIP" install -q --upgrade openpyxl xlrd odfpy python-docx python-pptx pypdf pdfplumber pymupdf markdown
# Biology
"$PIP" install -q --upgrade biopython || echo "biopython failed (non-fatal)"
"$PIP" install -q --upgrade scikit-bio || echo "scikit-bio failed (non-fatal)"

log "Checking key tools"
for t in pandoc xelatex lualatex latexmk biber soffice pdftotext tesseract ocrmypdf R claude codex; do
  if command -v "$t" >/dev/null 2>&1; then echo "  ok   $t"; else echo "  MISSING $t"; fi
done
"$VENV/bin/python" -c "import fastapi, uvicorn, statsmodels, seaborn, pingouin, docx, pypdf, fitz, pyotp, qrcode; print('  ok   python stack')"
