Mika (29 contributions)
- Stardust-minus (29 contributions)
- Whale-Dolphin (20 contributions)
- pre-commit-ci[bot] (16 contributions)
- wishhyt (5 contributions)
- Enucatl (4 contributions)
- Tps-F (3 contributions)
- v3ucn (3 contributions)

---

## README

 
 Fish Speech 

**English** | [简体中文](docs/README.zh.md) | [Portuguese](docs/README.pt-BR.md) | [日本語](docs/README.ja.md) | [한국어](docs/README.ko.md) | [العربية](docs/README.ar.md) | [Español](docs/README.es.md) 

 
 
 
 
 
 
 

 
 
 

 

 
 
 
 
 
 
 
 
 
 
 

 
 
 
 
 
 
 
 
 
 
 

> [!IMPORTANT]
> **License Notice** 
> This codebase and its associated model weights are released under **[FISH AUDIO RESEARCH LICENSE](LICENSE)**. Please refer to [LICENSE](LICENSE) for more details. We will take action against any violation of the license.

> [!WARNING]
> **Legal Disclaimer** 
> We do not hold any responsibility for any illegal usage of the codebase. Please refer to your local laws about DMCA and other related laws.

## Quick Start

### For Human

Here are the official documents for Fish Audio S2, follow the instructions to get started easily.

- [Installation](https://speech.fish.audio/install/)
- [Command Line Inference](https://speech.fish.audio/inference/#command-line-inference)
- [WebUI Inference](https://speech.fish.audio/inference/#webui-inference)
- [Server Inference](https://speech.fish.audio/server/)
- [Docker Setup](https://speech.fish.audio/install/#docker-setup)

> [!IMPORTANT]
> **For SGLang server, please read [SGLang-Omni README](https://github.com/sgl-project/sglang-omni/blob/main/sglang_omni/models/fishaudio_s2_pro/README.md).**
>
> **For vLLM Omni server, please read [vLLM-Omni Fish Speech S2 Pro Recipe](https://github.com/vllm-project/vllm-omni/blob/main/recipes/fishaudio/Fish-Speech-S2-Pro.md) and the [User Guide](https://github.com/vllm-project/vllm-omni/blob/main/docs/user_guide/examples/online_serving/text_to_speech.md#fish-speech-s2-pro).**

### For LLM Agent

```
Install and configure Fish-Audio S2 by following the instructions here: https://speech.fish.audio/install/
```

## Fish Audio S2 Pro
**State-of-the-art multilingual text-to-speech (TTS) system, redefining the boundaries of voice generation.**

Fish Audio S2 Pro is the most advanced multimodal model developed by [Fish Audio](https://fish.audio/). Trained on over **10 million hours** of audio data covering more than **80 languages**, S2 Pro combines a **Dual-Autoregressive (Dual-AR)** architecture with reinforcement learning (RL) alignment to generate speech that is exceptionally natural, realistic, and emotionally rich, leading the competition among both open-source and closed-source systems.

The core strength of S2 Pro lies in its support for **sub-word level** fine-grained control of prosody and emotion using natural language tags (e.g., `[whisper]`, `[excited]`, `[angry]`), while natively supporting multi-speaker and multi-turn conversation generation.

Visit the [Fish Audio website](https://fish.audio/) for a live playground, or read our [technical report](https://arxiv.org/abs/2603.08823) and [blog post](https://fish.audio/blog/fish-audio-open-sources-s2/) for more details.

### Model Variants

| Model | Size | Availability | Description |
|------|------|-------------|-------------|
| S2-Pro | 4B parameters | [HuggingFace](https://huggingface.co/fishaudio/s2-pro) | Full-featured flagship model with maximum quality and stability |

More details of the model can be found in the [technical report](https://arxiv.org/abs/2411.01156).

## Benchmark Results

| Benchmark | Fish Audio S2 |
|------|------|
| Seed-TTS Eval — WER (Chinese) | **0.54%** (best overall) |
| Seed-TTS Eval — WER (English) | **0.99%** (best overall) |
| Audio Turing Test (with instruction) | **0.515** posterior mean |
| EmergentTTS-Eval — Win Rate | **81.88%** (highest overall) |
| Fish Instruction Benchmark — TAR | **93.3%** |
| Fish Instruction Benchmark — Quality | **4.51 / 5.0** |
| Multilingual (MiniMax Testset) — Best WER | **11 of 24** languages |
| Multilingual (MiniMax Testset) — Best SIM | **17 of 24** languages |

On Seed-TTS Eval, S2 achieves the lowest WER among all evaluated models including closed-source systems: Qwen3-TTS (0.77/1.24), MiniMax Speech-02 (0.99/1.90), Seed-TTS (1.12/2.25). On the Audio Turing Test, 0.515 surpasses Seed-TTS (0.417) by 24% and MiniMax-Speech (0.387) by 33%. On EmergentTTS-Eval, S2 achieves particularly strong results in paralinguistics (91.61% win rate), questions (84.41%), and syntactic complexity (83.39%).

## Highlights

 

### Fine-Grained Inline Control via Natural Language

S2 Pro brings unprecedented \"soul\" to speech. Using simple `[tag]` syntax, you can precisely embed emotional instructions at any position in the text.
- **15,000+ Unique Tags Supported**: Not limited to fixed presets; S2 supports **free-form text descriptions**. Try `[whisper in small voice]`, `[professional broadcast tone]`, or `[pitch up]`.
- **Rich Emotion Library**:
 `[pause]` `[emphasis]` `[laughing]` `[inhale]` `[chuckle]` `[tsk]` `[singing]` `[excited]` `[laughing tone]` `[interrupting]` `[chuckling]` `[excited tone]` `[volume up]` `[echo]` `[angry]` `[low volume]` `[sigh]` `[low voice]` `[whisper]` `[screaming]` `[shouting]` `[loud]` `[surprised]` `[short pause]` `[exhale]` `[delight]` `[panting]` `[audience laughter]` `[with strong accent]` `[volume down]` `[clearing throat]` `[sad]` `[moaning]` `[shocked]`

### Innovative Dual-Autoregressive (Dual-AR) Architecture

S2 Pro adopts a master-slave Dual-AR architecture consisting of a decoder-only transformer and an RVQ audio codec (10 codebooks, ~21 Hz):

- **Slow AR (4B parameters)**: Operates along the time axis, predicting the primary semantic codebook.
- **Fast AR (400M parameters)**: Generates the remaining 9 residual codebooks at each time step, reconstructing exquisite acoustic details.

This asymmetric design achieves peak audio fidelity while significantly boosting inference speed.

### Reinforcement Learning (RL) Alignment

S2 Pro utilizes **Group Relative Policy Optimization (GRPO)** for post-training alignment. We use the same model suite for data cleaning and annotation directly as Reward Models, perfectly resolving the distribution mismatch bet