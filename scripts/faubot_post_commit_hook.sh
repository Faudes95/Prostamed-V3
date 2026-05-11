#!/bin/bash
# Faubot 2026-04-25 (LXX) — Auditoría #65A
# Post-commit hook que automatiza versioning + changelog generation.
#
# Comportamiento:
#   1. Lee el último commit message
#   2. Si menciona "Faubot 2026-04-XX (NUMERAL)" → bumpea FAUBOT_RELEASE
#   3. Si NO menciona Faubot release → solo agrega entry en CHANGELOG.md
#   4. Genera/actualiza CHANGELOG.md con entry markdown formateado
#
# Instalación:
#   ln -s ../../scripts/faubot_post_commit_hook.sh .git/hooks/post-commit
#   chmod +x scripts/faubot_post_commit_hook.sh
#
# Skip con: SKIP_FAUBOT_HOOK=1 git commit ...

if [ "$SKIP_FAUBOT_HOOK" = "1" ]; then
    exit 0
fi

set -e
PROJECT_ROOT="$(cd "$(dirname "$0")/.." && pwd)"
ALGO_VERSION_FILE="$PROJECT_ROOT/prostanet/shared/algorithm_version.py"
CHANGELOG_FILE="$PROJECT_ROOT/CHANGELOG.md"

# Step 1: Get last commit message
LAST_COMMIT_MSG=$(git -C "$PROJECT_ROOT" log -1 --pretty=%B)
LAST_COMMIT_HASH=$(git -C "$PROJECT_ROOT" log -1 --pretty=%H)
LAST_COMMIT_DATE=$(git -C "$PROJECT_ROOT" log -1 --pretty=%ad --date=short)
LAST_COMMIT_TITLE=$(echo "$LAST_COMMIT_MSG" | head -1)

# Step 2: Try to extract Faubot release if mentioned in commit
# Pattern: "Faubot YYYY-MM-DD ROMAN" (e.g., "Faubot 2026-04-25 LXX")
FAUBOT_RELEASE_PATTERN='Faubot ([0-9]{4}-[0-9]{2}-[0-9]{2}) ([IVXLCDM]+)'
if [[ "$LAST_COMMIT_MSG" =~ $FAUBOT_RELEASE_PATTERN ]]; then
    DETECTED_DATE="${BASH_REMATCH[1]}"
    DETECTED_NUMERAL="${BASH_REMATCH[2]}"
    NEW_RELEASE="$DETECTED_DATE $DETECTED_NUMERAL"

    # Get current FAUBOT_RELEASE from algorithm_version.py
    CURRENT_RELEASE=$(grep "^FAUBOT_RELEASE = " "$ALGO_VERSION_FILE" | sed 's/FAUBOT_RELEASE = "\([^"]*\)"/\1/')

    if [ "$CURRENT_RELEASE" != "$NEW_RELEASE" ]; then
        echo "[Faubot post-commit] Bumping FAUBOT_RELEASE: '$CURRENT_RELEASE' → '$NEW_RELEASE'"
        # Sed in place (BSD/macOS compatible)
        sed -i.bak "s|^FAUBOT_RELEASE = .*|FAUBOT_RELEASE = \"$NEW_RELEASE\"|" "$ALGO_VERSION_FILE"
        rm -f "$ALGO_VERSION_FILE.bak"
        echo "[Faubot post-commit] ⚠️  algorithm_version.py modified; commit again to include the bump"
    fi
fi

# Step 3: Append to CHANGELOG.md
if [ ! -f "$CHANGELOG_FILE" ]; then
    cat > "$CHANGELOG_FILE" <<EOF
# CHANGELOG — ProstaNet/ProstaMed

> Generado automáticamente por \`faubot_post_commit_hook.sh\` (Faubot LXX #65A).
> Cada commit en el bucle Faubot agrega una entry estructurada con
> referencia al hash + release + fecha.

EOF
fi

# Append entry only if hash not already present (idempotente)
if ! grep -q "$LAST_COMMIT_HASH" "$CHANGELOG_FILE" 2>/dev/null; then
    {
        echo ""
        echo "## $LAST_COMMIT_DATE — \`${LAST_COMMIT_HASH:0:8}\`"
        echo ""
        echo "$LAST_COMMIT_TITLE"
        if [ -n "$NEW_RELEASE" ]; then
            echo ""
            echo "**Faubot release**: \`$NEW_RELEASE\`"
        fi
        echo ""
    } >> "$CHANGELOG_FILE"
    echo "[Faubot post-commit] CHANGELOG.md updated with $LAST_COMMIT_HASH"
fi

exit 0
