# Running Cadence on Azure

One Ubuntu VM runs the production stack (`docker-compose.prod.yml` + `docker-compose.azure.yml`): the login
database, login service, Cadence API with the Telegram bot, the dashboard, and Caddy, which provides HTTPS and
routes everything through one address. Data lives in Docker volumes on the VM's disk (the project database is a
SQLite file, which needs a real disk, not network storage).

| | |
|---|---|
| Site | https://cadence-sj-959c69.centralindia.cloudapp.azure.com |
| Resource group | `cadence-rg` (centralindia) |
| VM | `cadence-vm`, Standard_B2as_v2 (2 vCPU, 8 GB), Ubuntu 22.04, 40 GB disk |
| Login | `ssh -i ~/.ssh/cadence_azure azureuser@<site address>` (allowed only from the IP set in the `ssh-from-admin` rule) |
| App folder on the VM | `~/cadence` (a clone of this repo; `.env` is there, owner-only) |

Always pass `--subscription` to `az` if more than one account is signed in.

## Day-to-day

```bash
SUB=<subscription id>; ssh -i ~/.ssh/cadence_azure azureuser@<site address>
cd ~/cadence
docker compose -f docker-compose.prod.yml -f docker-compose.azure.yml ps          # status
docker compose -f docker-compose.prod.yml -f docker-compose.azure.yml logs -f cadence
git pull && docker compose -f docker-compose.prod.yml -f docker-compose.azure.yml up -d --build   # update
```

- **SSH stopped working** (your IP changed): `az network nsg rule update -g cadence-rg --nsg-name cadence-nsg -n ssh-from-admin --source-address-prefixes <new ip>/32 --subscription $SUB`
- **Stop paying for the VM** (keeps the disk, which still costs a little): `az vm deallocate -g cadence-rg -n cadence-vm --subscription $SUB`; start again with `az vm start ...`. The public IP is static, so the address does not change.
- **Remove everything**: `az group delete -n cadence-rg --subscription $SUB` (deletes the data too).

## Rules that matter

- **One bot copy.** Telegram lets only one program poll a token. The token on this server must not be in any laptop
  or other server's `.env`. If `/api/health` shows `telegram: conflict`, something else is running with the token.
- **Back up** the `cadence_data` and `pgdata` volumes before risky changes, for example
  `docker run --rm -v cadence_cadence_data:/d -v $PWD:/b alpine tar czf /b/cadence-data.tgz -C /d .`.
- `DEMO_MODE` is `false` here. Google sign-in and password-reset email are not configured.
