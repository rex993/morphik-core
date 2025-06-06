# Fork Management Workflow

## Overview

This guide covers best practices for managing a forked repository where:
- `main` branch stays synced with the upstream repository
- `dev` branch contains your custom development work
- `stable` branch contains production-ready releases
- You periodically incorporate upstream changes into your work

## Strategy Comparison

### Strategy 1: Periodic Merge (Recommended for most cases)
Periodically merge upstream changes through your main branch:

```bash
# Weekly or bi-weekly
./sync-upstream.sh
# Choose 'y' to merge main into dev
```

**Pros:**
- Preserves your commit history
- Easier to track what changes came from upstream vs your work
- Less risky - conflicts are resolved incrementally

**Cons:**
- Creates merge commits in your history
- Can get messy if done too frequently

### Strategy 2: Rebase Strategy (For cleaner history)
Rebase your dev branch on top of latest upstream:

```bash
# Fetch and rebase your dev branch on top of latest main
git checkout dev
git fetch upstream
git rebase upstream/main
```

**Pros:**
- Cleaner, linear history
- Your changes appear "on top" of upstream

**Cons:**
- Rewrites history (requires force push)
- More complex conflict resolution
- Not good if others are working on your dev branch

### Strategy 3: Feature Branch Strategy (Most professional)
Keep `dev` stable and use feature branches:

```bash
# Create feature branch from latest main
git fetch upstream
git checkout -b feature/my-feature upstream/main

# When done, merge to dev
git checkout dev
git merge feature/my-feature

# Periodically rebase dev
git rebase upstream/main
```

## Recommended Hybrid Approach

### 1. Daily Development
- Work on feature branches created from `dev`
- Merge completed features back to `dev`
- Push `dev` regularly to backup your work

### 2. Weekly Sync (Every Monday)
```bash
# Run the sync script
./sync-upstream.sh

# Or manually:
git fetch upstream
git checkout main
git reset --hard upstream/main
git push origin main --force
git checkout dev
git merge main
```

### 3. Before Starting Major Features
Always sync before starting something big:
```bash
# Sync main
./sync-upstream.sh

# Create feature branch from updated dev
git checkout dev
git checkout -b feature/major-feature
```

### 4. Feature Isolation
```bash
# For upstream contributions
git checkout -b feature/name upstream/main

# For your custom features  
git checkout -b feature/name dev
```

### 5. Release Strategy with Stable Branch
Maintain a dedicated `stable` branch for production releases:
```bash
# When dev is ready for production
git checkout dev
git pull origin dev

# Run tests, ensure everything works

# Merge to stable
git checkout stable
git merge dev --no-ff -m "Release v1.2.0: Description of changes"
git tag v1.2.0
git push origin stable --tags
```

### 6. Hotfix Workflow (for urgent stable fixes)
```bash
# Create hotfix from stable
git checkout stable
git checkout -b hotfix/critical-fix
# ... fix ...
git commit

# Merge to stable
git checkout stable
git merge hotfix/critical-fix --no-ff
git tag v1.2.1

# Backport to dev
git checkout dev
git merge hotfix/critical-fix
```

### 7. Safety Measures
```bash
# Before risky syncs
git branch dev-backup

# Create tags for important states
git tag dev-stable-2024-12
```

## Stable Branch Workflow (Recommended)

### Branch Structure
- **`main`** - Mirrors upstream repository (always clean)
- **`dev`** - Active development with all your custom features  
- **`stable`** - Production-ready releases from dev

### Daily Development Flow
```bash
# Work on feature branches from dev
git checkout dev
git checkout -b feature/new-feature
# ... work ...
git commit
git checkout dev
git merge feature/new-feature
```

### Release Management

**When to update stable:**
- ✅ After thorough testing on dev
- ✅ When you need a production deployment
- ✅ After significant feature completion
- ✅ Before major upstream changes (preserve working version)

**When NOT to update stable:**
- ❌ Directly after upstream sync (test first!)
- ❌ With experimental features
- ❌ Without proper testing

**Branch Protection Best Practices:**
- Keep `stable` protected - no direct commits
- Always merge from `dev` or hotfix branches
- Tag every stable release
- Consider automated tests before allowing merges

### Complete Release Process
```bash
# 1. Ensure dev has latest upstream
./sync-upstream.sh

# 2. Test thoroughly on dev branch
# Run full test suite, manual testing, etc.

# 3. When ready, promote to stable
git checkout stable
git merge dev --no-ff -m "Release v1.3.0: Add LibreOffice support"
git tag v1.3.0
git push origin stable --tags

# 4. Deploy from stable branch
```

This approach gives you:
- `main` for tracking upstream
- `dev` for active development and experimentation
- `stable` for production deployments with confidence

## Best Practices

### When to Sync
- ✅ Every 1-2 weeks minimum
- ✅ Before starting major features
- ✅ When you see important updates in upstream
- ✅ Before creating PRs to upstream
- ✅ After upstream releases

### When NOT to Sync
- ❌ In the middle of a feature
- ❌ Daily (too frequent, creates noise)
- ❌ When upstream is unstable
- ❌ During critical development periods

### Handling Conflicts
1. Always sync when your working tree is clean
2. Resolve conflicts carefully - understand both changes
3. Test thoroughly after merging
4. Consider creating a backup branch before major syncs:
   ```bash
   git checkout dev
   git branch dev-backup
   ```

## Quick Decision Guide

**Use Merge (default)** when:
- You want to preserve history
- Multiple people work on your fork
- You have long-running custom features

**Use Rebase** when:
- You want a clean history
- You're working alone
- Your changes are small and focused

**Skip sync** when:
- You're in the middle of complex work
- Upstream is going through major refactoring
- You need stability for a release

## Alternative: Topic Branches from Upstream

For contributing back to upstream:
```bash
# Create feature branch from upstream/main
git fetch upstream
git checkout -b feature/contribution upstream/main

# Work on feature
git add .
git commit -m "Add feature"

# Push to your fork
git push origin feature/contribution

# Create PR from your fork to upstream
```

## Emergency Recovery

If something goes wrong:
```bash
# Reset dev to your last known good state
git checkout dev
git reset --hard origin/dev

# Or restore from backup
git checkout dev-backup
git branch -D dev
git branch -m dev
```

## Key Takeaway

The key is finding a rhythm that works for you - not too frequent (causes churn) but not too rare (causes massive conflicts). The hybrid approach with weekly syncs and strategic sync points before major work tends to work best for most fork management scenarios.