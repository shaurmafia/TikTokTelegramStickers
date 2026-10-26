@echo off
rem Remove the native messaging host registration.
rem Usage: uninstall_host.bat [--browser chrome^|edge^|both] [--purge]
python "%~dp0uninstall_host.py" %*
