@echo off
REM Voltage Ramp Script for QDQ-A01
REM Ramps from 0V to 60V in 30 seconds
REM Midpoint (40V) reached at 15 seconds

setlocal EnableDelayedExpansion

set COMPORT=COM3
set DEVICEID=1
set SETCOM=setcom.exe

echo ========================================
echo QDQ-A01 Voltage Ramp (Opaque)
echo ========================================
echo COM Port: %COMPORT%
echo Device ID: %DEVICEID%
echo Target: 0V to 60V in 30 seconds
echo Curve: Exponential (40V at midpoint)
echo ========================================
echo.

echo [00s] Setting voltage to 0.0V
%SETCOM% %COMPORT% %DEVICEID% 0.0
timeout /t 1 /nobreak >nul

echo [01s] Setting voltage to 1.5V
%SETCOM% %COMPORT% %DEVICEID% 1.5
timeout /t 1 /nobreak >nul

echo [02s] Setting voltage to 3.5V
%SETCOM% %COMPORT% %DEVICEID% 3.5
timeout /t 1 /nobreak >nul

echo [03s] Setting voltage to 5.5V
%SETCOM% %COMPORT% %DEVICEID% 5.5
timeout /t 1 /nobreak >nul

echo [04s] Setting voltage to 8.0V
%SETCOM% %COMPORT% %DEVICEID% 8.0
timeout /t 1 /nobreak >nul

echo [05s] Setting voltage to 10.5V
%SETCOM% %COMPORT% %DEVICEID% 10.5
timeout /t 1 /nobreak >nul

echo [06s] Setting voltage to 13.0V
%SETCOM% %COMPORT% %DEVICEID% 13.0
timeout /t 1 /nobreak >nul

echo [07s] Setting voltage to 16.0V
%SETCOM% %COMPORT% %DEVICEID% 16.0
timeout /t 1 /nobreak >nul

echo [08s] Setting voltage to 19.0V
%SETCOM% %COMPORT% %DEVICEID% 19.0
timeout /t 1 /nobreak >nul

echo [09s] Setting voltage to 22.0V
%SETCOM% %COMPORT% %DEVICEID% 22.0
timeout /t 1 /nobreak >nul

echo [10s] Setting voltage to 25.0V
%SETCOM% %COMPORT% %DEVICEID% 25.0
timeout /t 1 /nobreak >nul

echo [11s] Setting voltage to 28.0V
%SETCOM% %COMPORT% %DEVICEID% 28.0
timeout /t 1 /nobreak >nul

echo [12s] Setting voltage to 31.0V
%SETCOM% %COMPORT% %DEVICEID% 31.0
timeout /t 1 /nobreak >nul

echo [13s] Setting voltage to 34.0V
%SETCOM% %COMPORT% %DEVICEID% 34.0
timeout /t 1 /nobreak >nul

echo [14s] Setting voltage to 37.0V
%SETCOM% %COMPORT% %DEVICEID% 37.0
timeout /t 1 /nobreak >nul

echo [15s] Setting voltage to 40.0V  ** MIDPOINT **
%SETCOM% %COMPORT% %DEVICEID% 40.0
timeout /t 1 /nobreak >nul

echo [16s] Setting voltage to 40.5V
%SETCOM% %COMPORT% %DEVICEID% 40.5
timeout /t 1 /nobreak >nul

echo [17s] Setting voltage to 41.0V
%SETCOM% %COMPORT% %DEVICEID% 41.0
timeout /t 1 /nobreak >nul

echo [18s] Setting voltage to 42.0V
%SETCOM% %COMPORT% %DEVICEID% 42.0
timeout /t 1 /nobreak >nul

echo [19s] Setting voltage to 43.5V
%SETCOM% %COMPORT% %DEVICEID% 43.5
timeout /t 1 /nobreak >nul

echo [20s] Setting voltage to 45.0V
%SETCOM% %COMPORT% %DEVICEID% 45.0
timeout /t 1 /nobreak >nul

echo [21s] Setting voltage to 46.5V
%SETCOM% %COMPORT% %DEVICEID% 46.5
timeout /t 1 /nobreak >nul

echo [22s] Setting voltage to 48.0V
%SETCOM% %COMPORT% %DEVICEID% 48.0
timeout /t 1 /nobreak >nul

echo [23s] Setting voltage to 49.5V
%SETCOM% %COMPORT% %DEVICEID% 49.5
timeout /t 1 /nobreak >nul

echo [24s] Setting voltage to 51.0V
%SETCOM% %COMPORT% %DEVICEID% 51.0
timeout /t 1 /nobreak >nul

echo [25s] Setting voltage to 52.5V
%SETCOM% %COMPORT% %DEVICEID% 52.5
timeout /t 1 /nobreak >nul

echo [26s] Setting voltage to 54.0V
%SETCOM% %COMPORT% %DEVICEID% 54.0
timeout /t 1 /nobreak >nul

echo [27s] Setting voltage to 55.5V
%SETCOM% %COMPORT% %DEVICEID% 55.5
timeout /t 1 /nobreak >nul

echo [28s] Setting voltage to 57.0V
%SETCOM% %COMPORT% %DEVICEID% 57.0
timeout /t 1 /nobreak >nul

echo [29s] Setting voltage to 58.5V
%SETCOM% %COMPORT% %DEVICEID% 58.5
timeout /t 1 /nobreak >nul

echo [30s] Setting voltage to 60.0V  ** COMPLETE **
%SETCOM% %COMPORT% %DEVICEID% 60.0

echo.
echo ========================================
echo Voltage ramp complete!
echo Final voltage: 60.0V
echo ========================================

endlocal
