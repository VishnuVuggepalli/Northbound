# share/ — onboarding kit

Hand this folder to a new Northbound user or operator. It's the "getting started"
bundle: how the app works, how to log in, and how to drive it from the API.

| File | For |
|---|---|
| [`getting-started.md`](getting-started.md) | New users — roles, the request lifecycle, file → review → apply, the comment thread |
| [`api-walkthrough.sh`](api-walkthrough.sh) | A runnable curl flow: log in, list devices, file a VLAN request, approve, apply, comment |

Config/secret templates are at the repo root: `../.env.example`,
`../config.example.toml`. Copy-paste API payloads are in [`../examples/`](../examples/).

> These are static docs/scripts checked into the repo — the app does not read
> them. Edit freely for your environment.
