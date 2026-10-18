name: Collect and analyze MSE deals

on:
  schedule:
    # Даваа–Баасан 13:30 (Улаанбаатар, UTC+8): хэлцэл цуглуулж, өдрийн тайлан гаргана
    - cron: "30 5 * * 1-5"
    # Баасан 14:00 (Улаанбаатар): Даваа–Баасан гарагийн 7 хоногийн тайлан гаргана
    - cron: "0 6 * * 5"
  workflow_dispatch:
    inputs:
      weekly:
        description: "7 хоногийн тайланг гаргах (сонгохгүй бол өдрийн тайлан)"
        type: boolean
        default: false

permissions:
  contents: write

# Хоёр ажил зэрэг ажиллаж commit мөргөлдөхөөс сэргийлнэ
concurrency:
  group: mse-report
  cancel-in-progress: false

env:
  TELEGRAM_BOT_TOKEN: ${{ secrets.TELEGRAM_BOT_TOKEN }}
  TELEGRAM_CHAT_ID: ${{ secrets.TELEGRAM_CHAT_ID }}

jobs:
  run:
    runs-on: ubuntu-latest
    steps:
      - uses: actions/checkout@v4
      - uses: actions/setup-python@v5
        with:
          python-version: "3.12"
      - run: pip install openpyxl pandas pillow

      - name: 0. Горим сонгох (өдөр эсвэл 7 хоног)
        id: mode
        run: |
          if [ "${{ github.event.schedule }}" = "0 6 * * 5" ] || [ "${{ inputs.weekly }}" = "true" ]; then
            echo "mode=weekly" >> "$GITHUB_OUTPUT"
          else
            echo "mode=daily" >> "$GITHUB_OUTPUT"
          fi

      - name: Зурагт хэрэгтэй фонт суулгах (зөвхөн 7 хоногийн тайланд)
        if: steps.mode.outputs.mode == 'weekly'
        run: sudo apt-get install -y --no-install-recommends fonts-liberation fonts-dejavu-core

      - name: 1. Хэлцэл цуглуулах
        run: python collect.py

      - name: 2. Өдрийн шинжилгээ
        if: always() && steps.mode.outputs.mode == 'daily'
        run: python analyze.py daily

      - name: 3. Өдрийн тайланг Telegram руу илгээх
        if: always() && steps.mode.outputs.mode == 'daily'
        continue-on-error: true
        run: python send_telegram.py reports/latest_daily.txt

      - name: 4. 7 хоногийн шинжилгээ ба Telegram (зөвхөн Баасан 14:00 эсвэл гараар)
        if: always() && steps.mode.outputs.mode == 'weekly'
        run: |
          if [ "${{ github.event_name }}" = "schedule" ]; then
            python analyze.py weekly-auto
          else
            python analyze.py weekly
          fi
          python send_telegram.py reports/latest_weekly.txt --photo reports/latest_weekly.png --caption reports/latest_weekly_caption.txt || true

      - name: 5. Үр дүнг хадгалах (commit)
        if: always()
        run: |
          mkdir -p data reports
          git config user.name "github-actions[bot]"
          git config user.email "41898282+github-actions[bot]@users.noreply.github.com"
          git add data reports
          git diff --cached --quiet || git commit -m "MSE deals & reports $(date -u +%F)"
          git push
