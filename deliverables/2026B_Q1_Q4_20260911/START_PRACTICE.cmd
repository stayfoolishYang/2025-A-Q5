@echo off
cd /d "%~dp0"
if exist "D:\Anaconda3\envs\torchgpu\python.exe" (
 "D:\Anaconda3\envs\torchgpu\python.exe" "%~dp0run.py" practice
) else (
 python "%~dp0run.py" practice
)
if errorlevel 1 pause
