# FL-Net Python Tool API

```bash
pip install FL-Net-Python-Tool-API
```

The package is imported as `pyfedappwrap` (`from pyfedappwrap.engine.runtime import FedDBEngine`).

Python SDK and runtime for building **FL-Net tools** ("apps"): local analyses, preprocessing/transformer
steps, exports and federated learning apps. You implement the logic; pyfedappwrap handles the communication
with the platform, `app.yml` configuration, metrics, result upload, login during development and federated
aggregation (including SMPC and differential privacy settings).

Part of FL-Net, the federated learning platform also behind PosyMed.


## Documentation

All documentation can be found on the FL-Net documentation site:
- [FL-Net documentation](https://federated-learning.net/documentation/)
- [Federated runtime](https://federated-learning.net/documentation/docs/contribution-guide/python-tool-api/federated-runtime): how the engine runs a federated run internally


## Development

```bash
pip install -e ".[dev]"
pytest
```

| Folder | Content |
|---|---|
| `pyfedappwrap/` | The package |
| `tests/` | Test suite, with test apps in `tests/apps/`, configs in `tests/configs/` and input data in `tests/data/` |
| `examples/` | Example apps for tool authors |
| `scripts/` | Local dev runners, started from the repository root (`python -m scripts.run_local`) |
| `docker/` | Base image Dockerfiles, built by `.github/workflows/docker.yml` |

Local settings go into `.env` (template: `.env.example`).


## License

[Apache License 2.0](LICENSE) © Institute for Computational Systems Biomedicine and contributors.
