#!/bin/bash
# CCG One-Click Setup Script for macOS/Linux
set -e

# Color codes for output
RED='\033[0;31m'
GREEN='\033[0;32m'
YELLOW='\033[1;33m'
CYAN='\033[0;36m'
NC='\033[0m' # No Color

# Get script directory
SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"

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
# Step 1: Check dependencies
# ==============================================================================
write_step "Step 1: Checking dependencies..."

# Check and install uv
if command -v uv &> /dev/null; then
    write_success "uv is installed"
else
    write_warning "uv is not installed, installing automatically..."
    if curl -LsSf https://astral.sh/uv/install.sh | sh; then
        export PATH="$HOME/.local/bin:$PATH"
        write_success "uv installed successfully"
    else
        write_error "Failed to install uv automatically"
        echo "Please install uv manually: https://github.com/astral-sh/uv"
        exit 1
    fi
fi

# Check gemini CLI
if command -v gemini &> /dev/null; then
    write_success "gemini CLI is installed"
else
    write_error "gemini CLI is not installed"
    echo "Please install Gemini CLI first: https://geminicli.com/docs/cli/install"
    exit 1
fi

# ==============================================================================
# Step 2: Install project dependencies
# ==============================================================================
write_step "Step 2: Installing project dependencies..."

cd "$SCRIPT_DIR"
if uv sync; then
    write_success "Project dependencies installed"
else
    write_error "Failed to install dependencies"
    exit 1
fi

# ==============================================================================
# Step 3: Register MCP server
# ==============================================================================
write_step "Step 3: Registering MCP server..."

# Try to remove existing ccg MCP server if it exists
gemini mcp remove ccg 2>/dev/null && write_warning "Removed existing ccg MCP server" || true

# Add CCG MCP server (Remote Source via uvx)
# Using the online repository ensures you're running the latest version without local dependency issues
REPO_URL="https://github.com/Nico-M/Gemini-Coder.git"

if gemini mcp add ccg --scope user uvx --from "git+$REPO_URL" ccg-mcp; then
    write_success "MCP server registered globally (Remote Source: $REPO_URL)"
else
    write_error "Failed to register MCP server"
    exit 1
fi

# ==============================================================================
# Step 4: Install Skills
# ==============================================================================
write_step "Step 4: Installing Skills..."

SKILLS_DIR="$HOME/.gemini/skills"
CCG_WORKFLOW_SOURCE="$SCRIPT_DIR/skills/ccg-workflow"
CLAUDE_COLLAB_SOURCE="$SCRIPT_DIR/skills/claude-collaboration"

# Create skills directory if it doesn't exist
if [ ! -d "$SKILLS_DIR" ]; then
    mkdir -p "$SKILLS_DIR"
    write_success "Created skills directory: $SKILLS_DIR"
fi

# Copy ccg-workflow skill
if [ -d "$CCG_WORKFLOW_SOURCE" ]; then
    DEST="$SKILLS_DIR/ccg-workflow"
    rm -rf "$DEST"
    cp -r "$CCG_WORKFLOW_SOURCE" "$DEST"
    write_success "Installed ccg-workflow skill"
else
    write_warning "ccg-workflow skill not found, skipping"
fi

# Copy claude-collaboration skill
if [ -d "$CLAUDE_COLLAB_SOURCE" ]; then
    DEST="$SKILLS_DIR/claude-collaboration"
    rm -rf "$DEST"
    cp -r "$CLAUDE_COLLAB_SOURCE" "$DEST"
    write_success "Installed claude-collaboration skill"
else
    write_warning "claude-collaboration skill not found, skipping"
fi

# Enable skills
if gemini skills enable ccg-workflow; then
    write_success "Enabled ccg-workflow skill"
else
    write_warning "Failed to enable ccg-workflow skill (it might already be enabled)"
fi

if gemini skills enable claude-collaboration; then
    write_success "Enabled claude-collaboration skill"
else
    write_warning "Failed to enable claude-collaboration skill (it might already be enabled)"
fi

# ==============================================================================
# Step 5: Configure global AGENTS.md
# ==============================================================================
write_step "Step 5: Configuring global AGENTS.md..."

AGENTS_MD_PATH="$HOME/.gemini/AGENTS.md"
CCG_MARKER="# CCG Configuration"
CCG_CONFIG_PATH="$SCRIPT_DIR/templates/ccg-global-prompt.md"

# Create .gemini directory if it doesn't exist
mkdir -p "$HOME/.gemini"

if [ ! -f "$AGENTS_MD_PATH" ]; then
    # Create new file with CCG config
    if [ -f "$CCG_CONFIG_PATH" ]; then
        cp "$CCG_CONFIG_PATH" "$AGENTS_MD_PATH"
        write_success "Created global AGENTS.md"
    else
        write_warning "CCG global prompt template not found at $CCG_CONFIG_PATH"
        write_warning "Please manually copy the CCG configuration to $AGENTS_MD_PATH"
    fi
else
    # Check if CCG config already exists
    if grep -qF "$CCG_MARKER" "$AGENTS_MD_PATH"; then
        write_warning "CCG configuration already exists in AGENTS.md, skipping"
    else
        # Append CCG config
        if [ -f "$CCG_CONFIG_PATH" ]; then
            echo "" >> "$AGENTS_MD_PATH"
            cat "$CCG_CONFIG_PATH" >> "$AGENTS_MD_PATH"
            write_success "Appended CCG configuration to AGENTS.md"
        else
            write_warning "CCG global prompt template not found at $CCG_CONFIG_PATH"
            write_warning "Please manually copy the CCG configuration to $AGENTS_MD_PATH"
        fi
    fi
fi

# ==============================================================================
# Step 6: Configure Coder
# ==============================================================================
write_step "Step 6: Configuring Coder..."

CONFIG_DIR="$HOME/.ccg-mcp"
CONFIG_PATH="$CONFIG_DIR/config.toml"

# Create config directory if it doesn't exist
mkdir -p "$CONFIG_DIR"

# Check if config already exists
if [ -f "$CONFIG_PATH" ]; then
    write_warning "Config file already exists at $CONFIG_PATH"
    read -p "Overwrite? (y/N): " OVERWRITE
    if [ "$OVERWRITE" != "y" ] && [ "$OVERWRITE" != "Y" ]; then
        write_warning "Skipping Coder configuration"
        # Jump to Done
        echo ""
        echo -e "${GREEN}============================================================${NC}"
        write_success "CCG setup completed successfully!"
        echo -e "${GREEN}============================================================${NC}"
        echo ""
        echo "Next steps:"
        echo "  1. Restart Gemini CLI"
        echo "  2. Verify MCP server: gemini mcp list"
        echo "  3. Check available skills: gemini skills list"
        echo ""
        exit 0
    fi
fi

# Prompt for API Token (hidden input)
read -s -p "Enter your API Token: " API_TOKEN
echo
if [ -z "$API_TOKEN" ]; then
    write_error "API Token is required"
    exit 1
fi

# Prompt for Base URL (optional)
read -p "Enter Base URL (default: https://open.bigmodel.cn/api/anthropic): " BASE_URL
if [ -z "$BASE_URL" ]; then
    BASE_URL="https://open.bigmodel.cn/api/anthropic"
fi

# Prompt for Model (optional)
read -p "Enter Model (default: glm-4.7): " MODEL
if [ -z "$MODEL" ]; then
    MODEL="glm-4.7"
fi

# Generate config.toml
cat > "$CONFIG_PATH" << EOF
[coder]
api_token = "$API_TOKEN"
base_url = "$BASE_URL"
model = "$MODEL"
EOF

write_success "Configuration saved to $CONFIG_PATH"

echo ""
echo -e "${GREEN}============================================================${NC}"
write_success "CCG setup completed successfully!"
echo -e "${GREEN}============================================================${NC}"
echo ""

echo "Next steps:"
echo "  1. Restart Gemini CLI"
echo "  2. Verify MCP server: gemini mcp list"
echo "  3. Check available skills: gemini skills list"
echo ""
