# sab

Runner for the SceneActBench tasks `recon-twin-bedroom` and `recon-den`. Each run is one Harbor trial on a
GitHub-hosted runner.

## Setup

Add these repository secrets (Settings > Secrets and variables > Actions):

- `CURSOR_API_KEY` (GLM 5.3 Flash through Cursor)
- `AI_GATEWAY_API_KEY` (Kimi K3 through the Vercel AI Gateway)

## Run

Actions > "SceneActBench run" > Run workflow:

- `task`: `recon-twin-bedroom` or `recon-den`
- `label`: name of the run, for example `golden-try1`, `golden-fb1` or `kimi-rollout1`
- `feedback_dir` (feedback rounds only): a folder with `feedback.md` and `previous_scene.glb`
- `model`: `cursor/glm-5p3-flash` for the golden solution, `moonshotai/kimi-k3` for rollouts

## Results

Each run pushes the branch `res/<task>-<label>` with `results/<task>/<label>/`.
