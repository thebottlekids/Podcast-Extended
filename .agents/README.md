# README - Podcast-AdBlock Documentation

## Welcome to the Podcast-AdBlock Documentation

This `.agents` folder contains comprehensive documentation for the **Podcast-AdBlock** podcast ad-blocking application. Podcast-AdBlock is a fork of [Podly](https://github.com/normand1/podly_pure_podcasts) with additional features and improvements.

**Main Repository**: https://github.com/mebezac/Podcast-AdBlock

⚠️ **Important**: All development work should target this fork, not the upstream repository. Please submit issues and pull requests to https://github.com/mebezac/Podcast-AdBlock.

This documentation is organized into focused sections for easy reference.

## Documentation Index

### Getting Started
1. **[01_project_overview.md](01_project_overview.md)** - What is Podly and how it works
2. **[08_configuration.md](08_configuration.md)** - Configuration system and settings
3. **[09_development.md](09_development.md)** - Development setup and guidelines

### Architecture
4. **[02_database_models.md](02_database_models.md)** - Database schema and models
5. **[03_api_routes.md](03_api_routes.md)** - API endpoints and routes
6. **[04_processing_pipeline.md](04_processing_pipeline.md)** - Audio processing workflow
7. **[05_writer_service.md](05_writer_service.md)** - Writer service and IPC architecture

### Features
8. **[06_authentication.md](06_authentication.md)** - Auth system and security
9. **[07_frontend.md](07_frontend.md)** - Frontend React application

### Operations
10. **[10_deployment.md](10_deployment.md)** - Deployment options and operations
11. **[11_testing.md](11_testing.md)** - Testing and quality assurance

## Quick Reference

### For New Developers
1. Read [01_project_overview.md](01_project_overview.md) to understand the project
2. Follow [09_development.md](09_development.md) for setup instructions
3. Review [02_database_models.md](02_database_models.md) for data structure

### For DevOps/Deployment
1. Start with [10_deployment.md](10_deployment.md) for deployment options
2. Check [08_configuration.md](08_configuration.md) for environment setup
3. Review [05_writer_service.md](05_writer_service.md) for architecture understanding

### For API Development
1. Review [03_api_routes.md](03_api_routes.md) for endpoint documentation
2. Check [06_authentication.md](06_authentication.md) for auth requirements
3. See [02_database_models.md](02_database_models.md) for data models

### For Audio Processing
1. Read [04_processing_pipeline.md](04_processing_pipeline.md) for workflow details
2. Check [08_configuration.md](08_configuration.md) for processing settings
3. Review [11_testing.md](11_testing.md) for testing approaches

## Key Concepts

### Dual-App Architecture
Podly uses a unique **reader/writer pattern** where:
- **Web App**: Handles HTTP requests (read-only database access)
- **Writer Service**: Dedicated process for all database writes

This prevents SQLite locking issues. See [05_writer_service.md](05_writer_service.md) for details.

### Processing Pipeline
Episodes are processed in 4 steps:
1. **Download** - Fetch audio from RSS
2. **Transcribe** - Whisper audio-to-text
3. **Classify** - LLM identifies ads
4. **Process** - FFmpeg removes ads

See [04_processing_pipeline.md](04_processing_pipeline.md) for the full workflow.

### Configuration Layers
Settings come from three sources:
1. **Environment Variables** (`.env.local`) - Secrets and deployment config
2. **Database Settings** - Editable via web UI
3. **Runtime Config** - In-memory singleton for fast access

See [08_configuration.md](08_configuration.md) for configuration details.

## Important Rules

⚠️ **Critical Development Rules:**

1. **Never use `db.session.commit()` directly** - Always use `writer_client.action()`
2. **All database writes go through the writer service** - Web app is read-only
3. **Do not create Alembic migrations yourself** - Ask the user to generate them
4. **Use `./scripts/ci.sh` for testing** - Don't run tests directly
5. **Use pipenv for Python** - As specified in project requirements

## Project Stats

- **Backend**: ~144 Python files
- **Frontend**: React + TypeScript + Vite
- **Database**: SQLite with WAL mode
- **Tests**: pytest with coverage reporting
- **Deployment**: Docker, Railway, or native

## External Documentation

- Main Repository: https://github.com/mebezac/Podcast-AdBlock
- Main README: `/workspace/repos/Podcast-AdBlock/README.md`
- Railway Guide: `docs/how_to_run_railway.md`
- Beginner's Guide: `docs/how_to_run_beginners.md`
- Contributing: `docs/contributors.md`

## Support

- **GitHub Issues**: https://github.com/mebezac/Podcast-AdBlock/issues (Report bugs and feature requests here)
- **Discord**: https://discord.gg/FRB98GtF6N
- **Preview Server**: https://podly.up.railway.app/

---

*This documentation is maintained as part of the Podcast-AdBlock project. Last updated: 2026-07-05*
