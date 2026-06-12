<h2 align="center">
<img width="50%" src="src/app/static/images/logos/logo_with_text.png" />

</h2>

<p align="center">
<p align="center">Ad-block for podcasts. Create an ad-free RSS feed.</p>
<p align="center">
  <a href="https://github.com/mebezac/Podcast-AdBlock" target="_blank">
    <img src="https://img.shields.io/badge/GitHub-Repo-blue.svg?logo=github&logoColor=white" alt="GitHub">
  </a>
  <a href="https://discord.gg/FRB98GtF6N" target="_blank">
      <img src="https://img.shields.io/badge/discord-join-blue.svg?logo=discord&logoColor=white" alt="Discord">
  </a>
</p>

## Overview

Podcast-AdBlock (a fork of Podly) uses Whisper and LLMs to remove ads from podcasts.

**This is a fork of [normand1/podly_pure_podcasts](https://github.com/normand1/podly_pure_podcasts) with additional features and improvements.**

🔗 **Main Repository**: https://github.com/mebezac/Podcast-AdBlock

<img width="100%" src="docs/images/screenshot.png" />

## How To Run

You have a few options to get started:

- [![Deploy on Railway](https://railway.com/button.svg)](https://railway.com/deploy/podly?referralCode=NMdeg5&utm_medium=integration&utm_source=template&utm_campaign=generic)
   - quick and easy setup in the cloud, follow our [Railway deployment guide](docs/how_to_run_railway.md). 
   - Use this if you want to share your Podly server with others.
- **Run Locally**: 
   - For local development and customization, 
   - see our [beginner's guide for running locally](docs/how_to_run_beginners.md). 
   - Use this for the most cost-optimal & private setup.
- **Run on Unraid**:
   - Self-host on your Unraid server with the included Docker template,
   - see the [Unraid deployment guide](docs/how_to_run_unraid.md).
   - Use this for a private, always-on setup on hardware you own.
- **[Join The Preview Server](https://podly.up.railway.app/)**: 
   - pay what you want (limited sign ups available)


## How it works:

- You request an episode
- Podly downloads the requested episode
- Whisper transcribes the episode
- LLM labels ad segments
- Podly removes the ad segments
- Podly delivers the ad-free version of the podcast to you

### Cost Breakdown
*Monthly cost breakdown for 5 podcasts*

| Cost    | Hosting  | Transcription | LLM    |
|---------|----------|---------------|--------|
| **free**| local    | local         | local  |
| **$2**  | local    | local         | remote |
| **$5**  | local    | remote        | remote |
| **$10** | public (railway)  | remote        | remote |
| **Pay What You Want** | [preview server](https://podly.up.railway.app/)    | n/a         | n/a  |
| **$5.99/mo** | https://zeroads.ai/ | production fork of podly | |


## Contributing

**Important**: This is a fork maintained at https://github.com/mebezac/Podcast-AdBlock

All contributions (pushes, pull requests, issues) should be made to **this fork**, not the original upstream repository.

- 🐛 **Bug Reports**: [Open an issue](https://github.com/mebezac/Podcast-AdBlock/issues)
- 🚀 **Feature Requests**: [Open an issue](https://github.com/mebezac/Podcast-AdBlock/issues)
- 💻 **Pull Requests**: Submit PRs to the `main` branch of this fork
- 📖 **Documentation**: See [contributing guide](docs/contributors.md) for local setup & contribution instructions

See [contributing guide](docs/contributors.md) for local setup & contribution instructions.
