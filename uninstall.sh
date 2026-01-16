#!/bin/bash
# CCG Uninstallation Script for macOS/Linux
set -e

# Color codes for output
RED='\033[0;31m'
GREEN='\033[0;32m'
YELLOW='\033[1;33m'
CYAN='\033[0;36m'
NC='\033[0m' # No Color

# Helper functions
write_step() {
    echo -e "\n${CYAN}[*] $1${NC}"
}

write_success() {
    echo -e "${GREEN}[OK] $1${NC}"
}

write_error() {
    echo -e "${RED}[ERROR] $1${NC}"
}

write_warning() {
    echo -e "${YELLOW}[WARN] $1${NC}"
}

# ==============================================================================
# Step 1: Remove MCP server
# ==============================================================================
write_step "Step 1: Removing MCP server..."

if command -v gemini &> /dev/null; then
    if gemini mcp remove ccg 2>/dev/null; then
        write_success "Removed ccg MCP server"
    else
        write_warning "ccg MCP server not found or already removed"
    fi
else
    write_error "gemini CLI is not installed, skipping MCP removal"
fi

# ==============================================================================
# Step 2: Remove Skills
# ==============================================================================
write_step "Step 2: Uninstalling Skills..."

SKILLS_DIR="$HOME/.gemini/skills"

# Disable skills first
if command -v gemini &> /dev/null; then
    gemini skills disable ccg-workflow 2>/dev/null && write_success "Disabled ccg-workflow skill" || true
    gemini skills disable claude-collaboration 2>/dev/null && write_success "Disabled claude-collaboration skill" || true
fi

# Remove skill directories
if [ -d "$SKILLS_DIR/ccg-workflow" ]; then
    rm -rf "$SKILLS_DIR/ccg-workflow"
    write_success "Removed ccg-workflow skill files"
fi

if [ -d "$SKILLS_DIR/claude-collaboration" ]; then
    rm -rf "$SKILLS_DIR/claude-collaboration"
    write_success "Removed claude-collaboration skill files"
fi

# ==============================================================================
# Step 3: Clean up AGENTS.md
# ==============================================================================
write_step "Step 3: Cleaning up AGENTS.md..."

AGENTS_MD_PATH="$HOME/.gemini/AGENTS.md"
CCG_MARKER="# CCG Configuration"

if [ -f "$AGENTS_MD_PATH" ]; then
    if grep -qF "$CCG_MARKER" "$AGENTS_MD_PATH"; then
        # Create a temporary file without the CCG section
        # This deletes from the marker line to the end of file
        sed -i "/$CCG_MARKER/,\$d" "$AGENTS_MD_PATH"
        write_success "Removed CCG configuration from AGENTS.md"
    else
        write_warning "CCG configuration marker not found in AGENTS.md"
    fi
else
    write_warning "AGENTS.md not found"
fi

# ==============================================================================
# Step 4: Remove Configuration (Optional)
# ==============================================================================
write_step "Step 4: Cleaning up local configuration..."

CONFIG_DIR="$HOME/.ccg-mcp"

if [ -d "$CONFIG_DIR" ]; then
    read -p "Do you want to remove the Coder configuration directory ($CONFIG_DIR)? (y/N): " REMOVE_CONFIG
    if [ "$REMOVE_CONFIG" = "y" ] || [ "$REMOVE_CONFIG" = "Y" ]; then
        rm -rf "$CONFIG_DIR"
        write_success "Removed $CONFIG_DIR"
    else
        write_warning "Skipped removing configuration directory"
    fi
else
    write_warning "Configuration directory not found"
fi

echo ""
echo -e "${GREEN}============================================================${NC}"
write_success "CCG uninstallation completed successfully!"
echo -e "${GREEN}============================================================${NC}"
echo ""
echo "Next steps:"
echo "  1. Restart Gemini CLI"
echo ""
