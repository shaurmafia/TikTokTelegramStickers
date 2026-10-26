@echo off
rem Install the native messaging host (per-user, no admin required).
rem Usage: install_host.bat --extension-id <32-letter ID> [--browser chrome^|edge^|both]
python "%~dp0install_host.py" %*
