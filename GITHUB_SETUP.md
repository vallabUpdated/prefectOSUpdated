# PrefectOS — GitHub repository setup & update workflow

## 1. Create the repo (one time, on github.com)
- New repository -> Owner: your account (or create org `prefectos`)
- Name: `prefectos` · **Private** · no README/gitignore (we bring our own)

## 2. First push (one time, on your Windows laptop, Git Bash)
    unzip prefectos_v8_2_repo_ready.zip && cd lc_lg_orchestrator_v2_Version6
    git init -b main
    bash scripts/install_hooks.sh        # secret scan guards every commit
    git add -A && git commit -m "PrefectOS v8.2 — batch agents, Bedrock, reports"
    git tag v8.2
    git remote add origin git@github.com:YOURNAME/prefectos.git
    git push -u origin main --tags
(Uses your existing GitHub SSH key. HTTPS + token works too.)

## 3. Connect the VM (one time) — read-only deploy key
On the VM:
    ssh-keygen -t ed25519 -f ~/.ssh/prefectos_deploy -N "" -C "gcp-pilot-vm"
    cat ~/.ssh/prefectos_deploy.pub
GitHub -> repo -> Settings -> Deploy keys -> Add (read-only). Then:
    cat >> ~/.ssh/config <<CFG
    Host github.com
      IdentityFile ~/.ssh/prefectos_deploy
    CFG
    mkdir -p ~/prefectos/data
    git clone git@github.com:YOURNAME/prefectos.git ~/prefectos/repo
    ln -sfn ~/prefectos/repo ~/prefectos/current
    ln -sfn ~/prefectos/data/projects        ~/prefectos/repo/projects
    ln -sfn ~/prefectos/data/project_output  ~/prefectos/repo/project_output
Point the systemd unit at WorkingDirectory=/home/vallab/prefectos/current
(read-only key = a compromised VM cannot alter your source).

## 4. Every update after that
Laptop:  edit -> commit -> `git push` (tag releases: `git tag v8.3 && git push --tags`)
VM:      `bash scripts/deploy.sh`          # main
         `bash scripts/deploy.sh v8.2`     # or any tag / instant rollback
deploy.sh restarts the service, health-checks /ingest/metrics, and
auto-rolls-back to the previous commit if the check fails.

## 5. Rules the repo enforces
- `.gitignore` keeps out: secrets/.env, ledgers & outputs (evidence stays in
  ~/prefectos/data, symlinked in), zips, caches, node_modules.
- `scripts/secret_scan.sh` blocks commits containing live Anthropic/AWS/
  Groq/GitHub/Google keys or private-key blocks. Test fixtures pass.
- History discipline: every release is a tag; `git log --oneline` is your
  version audit trail.
