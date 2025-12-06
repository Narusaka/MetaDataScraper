llama-server -m "$HOME/models/qwen3-4b.gguf" \
  --alias local-4b \
  --host 0.0.0.0 --port 32668 \
  --n-gpu-layers 32 \
  --temp 0.7 --top-p 0.9 --repeat-penalty 1.05 \
  -c 32768 \
  --mlock \
  --parallel 2