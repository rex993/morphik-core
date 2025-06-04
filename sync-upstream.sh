#!/bin/bash

# Colors for output
GREEN='\033[0;32m'
YELLOW='\033[1;33m'
RED='\033[0;31m'
NC='\033[0m' # No Color

echo -e "${YELLOW}=== Syncing with upstream Morphik repository ===${NC}"

# Store current branch
CURRENT_BRANCH=$(git branch --show-current)
echo -e "${GREEN}Current branch: ${CURRENT_BRANCH}${NC}"

# Fetch latest from upstream
echo -e "\n${YELLOW}Fetching upstream changes...${NC}"
git fetch upstream

# Sync main branch
echo -e "\n${YELLOW}Syncing main branch with upstream/main...${NC}"
git checkout main
git reset --hard upstream/main
git push origin main --force

# Return to previous branch
echo -e "\n${YELLOW}Returning to ${CURRENT_BRANCH}...${NC}"
git checkout $CURRENT_BRANCH

# Ask if user wants to merge main into current branch
echo -e "\n${YELLOW}Do you want to merge the updated main into ${CURRENT_BRANCH}? (y/n)${NC}"
read -r response
if [[ "$response" =~ ^([yY][eE][sS]|[yY])$ ]]
then
    echo -e "${YELLOW}Merging main into ${CURRENT_BRANCH}...${NC}"
    git merge main
    echo -e "${GREEN}Merge complete! Review any conflicts if they exist.${NC}"
else
    echo -e "${GREEN}Skipped merge. You can merge manually later with: git merge main${NC}"
fi

echo -e "\n${GREEN}✅ Sync complete!${NC}"