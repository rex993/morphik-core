# Fork Management Workflow

## Overview

This guide covers best practices for managing a forked repository where:
- `main` branch stays synced with the upstream repository
- `dev` branch contains your custom development work
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

### 5. Release Strategy
When you want to create a stable version:
```bash
# Create a release branch
git checkout dev
git checkout -b release/v1.0

# This preserves your stable version while dev continues
```

### 6. Safety Measures
```bash
# Before risky syncs
git branch dev-backup

# Create tags for important states
git tag dev-stable-2024-12
```

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