# OpenAgriNet Governance Enforcement

This repository enforces the policy in `Openagrinet-repo-ownership-and-pr-governance.pdf` with:

1. `CODEOWNERS` ownership mapping.
2. Pull request template checklist.
3. Automated PR governance checks in GitHub Actions.
4. Scripted branch protection for protected branches.

## What Is Enforced In-Repo

- Owners are defined in `.github/CODEOWNERS`.
- PRs into protected branches are validated by `.github/workflows/pr-governance.yml` for:
  - branch name pattern (`feature/`, `bugfix/`, `hotfix/`, `chore/`)
  - no self-approval
  - at least one peer approval
  - at least one CODEOWNERS approval
  - re-approval on latest commit
  - all review threads resolved

## Apply GitHub Branch Protection

Run:

```bash
bash scripts/apply_repo_governance.sh
```

Optional explicit target repo:

```bash
bash scripts/apply_repo_governance.sh <org>/<repo>
```

### Script Requirements

- `gh` installed and authenticated (`gh auth login`)
- admin access to the target repository
- `jq` installed

### Script Applies These Settings

For branches that exist among `main`, `master`, `mh-main`, `bh-main`:

- pull-request reviews required (minimum 1 approval)
- CODEOWNERS review required
- stale approvals dismissed on new commits
- last push requires approval from someone else
- all conversations must be resolved
- force pushes disabled
- branch deletions disabled
- admin enforcement enabled
- required status check: `PR Governance Gate / governance`
