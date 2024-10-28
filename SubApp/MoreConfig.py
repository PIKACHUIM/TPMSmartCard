import os


class MoreConfig:
    def __init__(self):
        pass

    @staticmethod
    def setupSSH():
        command = ("Set-ExecutionPolicy Bypass -Scope Process -Force;"
                   " [System.Net.ServicePointManager]::SecurityProtocol"
                   " = [System.Net.ServicePointManager]::SecurityProtocol"
                   " -bor 3072; iex ((New-Object System.Net.WebClient)"
                   ".DownloadString('https://community.chocolatey.org/install.ps1'))")
        os.system("powershell %s" % command)
        command = "choco install wincrypt-sshagent"
        os.system("powershell %s" % command)
        MoreConfig.startSSH()

    @staticmethod
    def startSSH():
        os.startfile("SSHCardAgent.exe")


if __name__ == "__main__":
    MoreConfig.setupSSH()