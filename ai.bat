@echo off
:: Mini AI - Global launcher
:: Place this in a directory on your PATH, or add the mini_ai_v39 folder to PATH
:: Usage: ai [options]
:: Example: ai --allow-run --copix

py "%~dp0run.py" --allow-run --copix %*
