@echo off

REM Check if argument is provided
IF "%~1"=="" (
    echo Usage: %0 ^<url_to_stream^>
    exit /B
)

REM Create torrc with HTTPTunnelPort setting
echo HTTPTunnelPort 9080 > %TEMP%\torrc

REM Start tor with the custom config
start /B tor.exe -f %TEMP%\torrc

REM Wait a little for tor to fully start up
timeout /T 10 /NOBREAK

REM Use ffplay to play the stream through the Tor network
set http_proxy=http://localhost:9080
ffplay %1

REM Kill the background tor process
taskkill /F /IM tor.exe /T

REM Remove the temporary torrc
del %TEMP%\torrc
