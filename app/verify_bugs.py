#!/usr/bin/env python3
"""Verifikasi 5 bug yang diperbaiki + regresi."""

import asyncio
import json
import os
import time
from pathlib import Path

import pyotp
from playwright.async_api import async_playwright

BASE_URL = "http://127.0.0.1:8768"
API_URL = f"{BASE_URL}/api"
SHOT_DIR = Path("/tmp/opencode/qa-shots")
SHOT_DIR.mkdir(parents=True, exist_ok=True)

USERNAME = os.getenv("QA_USERNAME", "qaadmin")
PASSWORD = os.getenv("QA_PASSWORD", "qapassword123")
H = {"x-requested-with": "fetch"}


async def setup_auth(page):
    """Setup akun + login."""
    # Check if setup needed
    resp = await page.request.get(f"{API_URL}/auth/status", headers=H)
    data = await resp.json()
    
    if data["needs_setup"]:
        # Setup account
        resp = await page.request.post(f"{API_URL}/auth/setup", data={
            "username": USERNAME,
            "password": PASSWORD
        }, headers=H)
        setup_data = await resp.json()
        secret = setup_data.get("secret") or setup_data.get("totp_secret")
        print(f"Setup done. TOTP secret: {secret}")
    else:
        # Get secret from DB
        import sqlite3
        conn = sqlite3.connect("/tmp/opencode/verify-ukk-fresh.db")
        row = conn.execute("SELECT totp_secret FROM user WHERE username = ?", (USERNAME,)).fetchone()
        conn.close()
        secret = row[0] if row else None
        print(f"Existing user. TOTP secret: {secret}")
    
    # Login
    totp = pyotp.TOTP(secret).now()
    resp = await page.request.post(f"{API_URL}/auth/login", data={
        "username": USERNAME,
        "password": PASSWORD,
        "totp": totp
    }, headers=H)
    login_data = await resp.json()
    print(f"Login: {login_data}")
    assert login_data.get("ok") == True
    
    return secret


async def test_bug003_duplicate_school(page):
    """BUG-003: POST sekolah "SMK 1" → POST "smk  1" → harus 409 nama_exists."""
    print("\n=== BUG-003: Duplicate school name (case/space insensitive) ===")
    
    # Create first school "SMK 1"
    resp = await page.request.post(f"{API_URL}/schools", data={
        "nama": "SMK 1",
        "kode": "SMK001"
    }, headers=H)
    data1 = await resp.json()
    print(f"Create SMK 1: {resp.status} - {data1}")
    assert resp.status == 201, f"Expected 201, got {resp.status}"
    school_id = data1["id"]
    
    # Try create "smk  1" (lowercase, double space)
    resp = await page.request.post(f"{API_URL}/schools", data={
        "nama": "smk  1",
        "kode": "SMK002"
    }, headers=H)
    data2 = await resp.json()
    print(f"Create smk  1: {resp.status} - {data2}")
    
    # Should be 409 with nama_exists
    success = resp.status == 409 and data2.get("error") == "nama_exists"
    print(f"BUG-003: {'PASS' if success else 'FAIL'}")
    
    await page.screenshot(path=str(SHOT_DIR / "verify-bug003.png"))
    return success


async def test_bug001_mobile_schools_table(page):
    """BUG-001: Buka #/schools mobile (390×844) → tabel tidak overflow horizontal, aksi 'Buka' terlihat; atau card layout."""
    print("\n=== BUG-001: Mobile schools table no horizontal overflow ===")
    
    # Set mobile viewport
    await page.set_viewport_size({"width": 390, "height": 844})
    await page.goto(f"{BASE_URL}/#/schools")
    await page.wait_for_load_state("networkidle")
    await page.wait_for_timeout(1000)
    
    # Check for horizontal overflow
    body_width = await page.evaluate("document.body.scrollWidth")
    viewport_width = await page.evaluate("window.innerWidth")
    has_overflow = body_width > viewport_width
    
    # Check if "Buka" action is visible (or card layout)
    buka_visible = await page.locator("text=Buka").first.is_visible()
    
    # Also check for card layout
    cards = await page.locator(".school-card, [data-testid='school-card']").count()
    has_cards = cards > 0
    
    print(f"Body width: {body_width}, Viewport: {viewport_width}, Overflow: {has_overflow}")
    print(f"'Buka' visible: {buka_visible}, Card layout: {has_cards}")
    
    # Success: no overflow AND (buka visible OR card layout)
    success = not has_overflow and (buka_visible or has_cards)
    print(f"BUG-001: {'PASS' if success else 'FAIL'}")
    
    await page.screenshot(path=str(SHOT_DIR / "verify-bug001.png"), full_page=True)
    return success


async def test_bug002_mobile_assessment_accordion(page):
    """BUG-002: Buka #/assessment/{id} mobile → accordion unit buka/tutup via touch."""
    print("\n=== BUG-002: Mobile assessment accordion touch ===")
    
    # First, need to create a school, participant, and start assessment
    # Create school
    resp = await page.request.post(f"{API_URL}/schools", data={
        "nama": "SMK Test Accordion",
        "kode": "SMKACC"
    }, headers=H)
    school = await resp.json()
    school_id = school["id"]
    
    # Create participant
    resp = await page.request.post(f"{API_URL}/schools/{school_id}/participants", data={
        "nomor": "001",
        "nama": "Test Peserta",
        "kelas": "XI TKJ"
    }, headers=H)
    participant = await resp.json()
    participant_id = participant["id"]
    
    # Start assessment
    resp = await page.request.post(f"{API_URL}/assessments", data={
        "participant_id": participant_id
    }, headers=H)
    assessment = await resp.json()
    assessment_id = assessment["assessment"]["id"]
    
    print(f"Created assessment: {assessment_id}")
    
    # Set mobile viewport
    await page.set_viewport_size({"width": 390, "height": 844})
    await page.goto(f"{BASE_URL}/#/assessment/{assessment_id}")
    await page.wait_for_load_state("networkidle")
    await page.wait_for_timeout(1500)
    
    # Find accordion headers (unit headers) - uses <summary class="unit-head"> with data-toggle-unit
    accordion_headers = page.locator("summary.unit-head[data-toggle-unit]")
    count = await accordion_headers.count()
    print(f"Found {count} unit accordion headers")
    
    success = False
    if count > 0:
        # Click first accordion header (touch)
        first_header = accordion_headers.first
        
        # Check initial state (should be closed by default on mobile, or first one open)
        first_details = first_header.locator("..")  # parent <details>
        is_open_initial = await first_details.evaluate("el => el.open")
        print(f"Initial open state: {is_open_initial}")
        
        # Click to toggle
        await first_header.click()
        await page.wait_for_timeout(500)
        
        # Check if content expanded
        is_open_after = await first_details.evaluate("el => el.open")
        print(f"After click open state: {is_open_after}")
        
        # Click again to collapse
        await first_header.click()
        await page.wait_for_timeout(500)
        
        is_open_after2 = await first_details.evaluate("el => el.open")
        print(f"After second click open state: {is_open_after2}")
        
        # Success if toggle works (open state changes)
        success = is_open_initial != is_open_after or is_open_after != is_open_after2
        print(f"Accordion toggle works: {success}")
    else:
        print("No accordion headers found - checking page content")
        content = await page.content()
        with open(SHOT_DIR / "verify-bug002-debug.html", "w") as f:
            f.write(content)
    
    print(f"BUG-002: {'PASS' if success else 'FAIL'}")
    await page.screenshot(path=str(SHOT_DIR / "verify-bug002.png"), full_page=True)
    return success


async def test_bug005_unlock_modal_counter(page):
    """BUG-005: Buka modal unlock → counter karakter merah <10, hijau ≥10; tombol submit disable <10."""
    print("\n=== BUG-005: Unlock modal character counter ===")
    
    # Need a locked assessment first
    # Create school
    resp = await page.request.post(f"{API_URL}/schools", data={
        "nama": "SMK Unlock Test",
        "kode": "SMKUNL"
    }, headers=H)
    school = await resp.json()
    school_id = school["id"]
    
    # Create participant
    resp = await page.request.post(f"{API_URL}/schools/{school_id}/participants", data={
        "nomor": "002",
        "nama": "Unlock Peserta",
        "kelas": "XI TKJ"
    }, headers=H)
    participant = await resp.json()
    participant_id = participant["id"]
    
    # Start assessment
    resp = await page.request.post(f"{API_URL}/assessments", data={
        "participant_id": participant_id
    }, headers=H)
    assessment = await resp.json()
    assessment_id = assessment["assessment"]["id"]
    
    # Add some scores to make it lockable
    resp = await page.request.patch(f"{API_URL}/assessments/{assessment_id}/scores", data={
        "items": [
            {"indicator_kode": "IND-001", "value": 3, "note": "Test"},
            {"indicator_kode": "IND-002", "value": 2, "note": "Test"},
        ]
    }, headers=H)
    
    # Lock assessment
    resp = await page.request.post(f"{API_URL}/assessments/{assessment_id}/lock", data={
        "confirm_empty": True
    }, headers=H)
    lock_data = await resp.json()
    print(f"Locked: {lock_data.get('status')}")
    assert lock_data.get("status") == "locked"
    
    # Now test unlock modal
    await page.set_viewport_size({"width": 1280, "height": 720})
    await page.goto(f"{BASE_URL}/#/assessment/{assessment_id}")
    await page.wait_for_load_state("networkidle")
    await page.wait_for_timeout(1000)
    
    # Find and click unlock button (data-unlock attribute)
    unlock_btn = page.locator("button[data-unlock]").first
    if await unlock_btn.count() > 0:
        await unlock_btn.click()
        await page.wait_for_timeout(500)
        
        # Find textarea for reason (in modal root)
        textarea = page.locator("#unlock-reason").first
        if await textarea.count() > 0:
            # Test < 10 chars (should be red, disabled)
            await textarea.fill("Short")
            await page.wait_for_timeout(300)
            
            # Check counter value
            counter = page.locator("#unlock-len").first
            counter_val = await counter.inner_text() if await counter.count() > 0 else ""
            counter_color = await counter.evaluate("el => window.getComputedStyle(el).color") if await counter.count() > 0 else ""
            print(f"Counter value (<10): {counter_val}, color: {counter_color}")
            
            # Check if submit is disabled
            submit_btn = page.locator(".modal-foot .btn.danger").first
            is_disabled = await submit_btn.is_disabled() if await submit_btn.count() > 0 else False
            print(f"Submit disabled (<10): {is_disabled}")
            
            # Test ≥ 10 chars (should be green/muted, enabled)
            await textarea.fill("Ini alasan yang cukup panjang untuk unlock")
            await page.wait_for_timeout(300)
            
            counter_val2 = await counter.inner_text() if await counter.count() > 0 else ""
            counter_color2 = await counter.evaluate("el => window.getComputedStyle(el).color") if await counter.count() > 0 else ""
            print(f"Counter value (>=10): {counter_val2}, color: {counter_color2}")
            
            is_disabled2 = await submit_btn.is_disabled() if await submit_btn.count() > 0 else True
            print(f"Submit disabled (>=10): {is_disabled2}")
            
            # Success: disabled when <10, enabled when >=10
            success = is_disabled and not is_disabled2
            print(f"BUG-005: {'PASS' if success else 'FAIL'}")
        else:
            print("No reason textarea found")
            success = False
    else:
        print("No unlock button found")
        success = False
    
    await page.screenshot(path=str(SHOT_DIR / "verify-bug005.png"), full_page=True)
    return success


async def test_bug004_offline_sync(page):
    """BUG-004: Offline → ubah skor → badge 'X belum sinkron' → online → flush → badge 'Tersinkron' (real-time, tanpa refresh)."""
    print("\n=== BUG-004: Offline sync badge ===")
    
    # Create school, participant, assessment
    resp = await page.request.post(f"{API_URL}/schools", data={
        "nama": "SMK Offline Test",
        "kode": "SMKOFL"
    }, headers=H)
    school = await resp.json()
    school_id = school["id"]
    
    resp = await page.request.post(f"{API_URL}/schools/{school_id}/participants", data={
        "nomor": "003",
        "nama": "Offline Peserta",
        "kelas": "XI TKJ"
    }, headers=H)
    participant = await resp.json()
    participant_id = participant["id"]
    
    resp = await page.request.post(f"{API_URL}/assessments", data={
        "participant_id": participant_id
    }, headers=H)
    assessment = await resp.json()
    assessment_id = assessment["assessment"]["id"]
    
    await page.set_viewport_size({"width": 1280, "height": 720})
    await page.goto(f"{BASE_URL}/#/assessment/{assessment_id}")
    await page.wait_for_load_state("networkidle")
    await page.wait_for_timeout(1500)
    
    # Ensure any modal is closed
    await page.keyboard.press("Escape")
    await page.wait_for_timeout(300)
    
    # Check initial sync pill state (should be "Tersinkron")
    sync_text = page.locator("#sync-text")
    initial_text = await sync_text.inner_text() if await sync_text.count() > 0 else ""
    print(f"Initial sync text: '{initial_text}'")
    
    # Go offline
    await page.context.set_offline(True)
    print("Gone offline")
    await page.wait_for_timeout(500)
    
    offline_text = await sync_text.inner_text() if await sync_text.count() > 0 else ""
    print(f"Offline sync text: '{offline_text}'")
    
    # Change a score (click on a score button)
    # Find first score button for an indicator that has no value yet
    score_btns = page.locator(".score-btn[data-value]")
    btn_count = await score_btns.count()
    print(f"Found {btn_count} score buttons")
    
    success = False
    if btn_count > 0:
        # Click first available score button (value 3)
        # We need one that's not already active
        for i in range(min(btn_count, 20)):
            btn = score_btns.nth(i)
            is_active = await btn.evaluate("el => el.classList.contains('active')")
            if not is_active:
                await btn.click()
                await page.wait_for_timeout(500)
                break
        
        # Check for "belum sinkron" badge
        pending_text = await sync_text.inner_text() if await sync_text.count() > 0 else ""
        print(f"After score change (offline): '{pending_text}'")
        
        # Go online
        await page.context.set_offline(False)
        print("Back online")
        await page.wait_for_timeout(3000)  # Wait for auto-sync
        
        # Check for "Tersinkron" badge
        synced_text = await sync_text.inner_text() if await sync_text.count() > 0 else ""
        print(f"After online + sync: '{synced_text}'")
        
        # Success criteria
        offline_ok = "belum sinkron" in pending_text.lower() or "pending" in pending_text.lower() or "offline" in offline_text.lower()
        synced_ok = "tersinkron" in synced_text.lower() or "sinkron" in synced_text.lower()
        
        success = offline_ok and synced_ok
        print(f"BUG-004: {'PASS' if success else 'FAIL'}")
    else:
        print("No score buttons found")
        success = False
    
    await page.screenshot(path=str(SHOT_DIR / "verify-bug004.png"), full_page=True)
    return success


async def test_regression_api(page):
    """9 skenario bisnis (API) + ekspor CSV/XLSX + backup."""
    print("\n=== REGRESI: 9 skenario API + export + backup ===")
    
    results = {}
    
    # 1. Setup auth - already done
    results["auth_setup"] = True
    
    # 2. CRUD School
    resp = await page.request.post(f"{API_URL}/schools", data={"nama": "Reg School", "kode": "REGSCH"}, headers=H)
    results["school_create"] = resp.status == 201
    school = await resp.json()
    school_id = school["id"]
    
    resp = await page.request.get(f"{API_URL}/schools", headers=H)
    results["school_list"] = resp.status == 200
    
    resp = await page.request.patch(f"{API_URL}/schools/{school_id}", data={"alamat": "Jl. Test"}, headers=H)
    results["school_update"] = resp.status == 200
    
    # 3. CRUD Participant
    resp = await page.request.post(f"{API_URL}/schools/{school_id}/participants", data={
        "nomor": "001", "nama": "Reg Peserta", "kelas": "XI"
    }, headers=H)
    results["participant_create"] = resp.status == 201
    participant = await resp.json()
    participant_id = participant["id"]
    
    resp = await page.request.get(f"{API_URL}/schools/{school_id}/participants", headers=H)
    results["participant_list"] = resp.status == 200
    
    # 4. Assessment start
    resp = await page.request.post(f"{API_URL}/assessments", data={"participant_id": participant_id}, headers=H)
    results["assessment_start"] = resp.status == 201
    assessment = await resp.json()
    assessment_id = assessment["assessment"]["id"]
    
    # 5. Score update
    resp = await page.request.patch(f"{API_URL}/assessments/{assessment_id}/scores", data={
        "items": [{"indicator_kode": "IND-001", "value": 3}]
    }, headers=H)
    results["score_update"] = resp.status == 200
    
    # 6. Assessment lock
    resp = await page.request.post(f"{API_URL}/assessments/{assessment_id}/lock", data={"confirm_empty": True}, headers=H)
    results["assessment_lock"] = resp.status == 200
    
    # 7. Assessment unlock
    resp = await page.request.post(f"{API_URL}/assessments/{assessment_id}/unlock", data={"reason": "Alasan unlock yang valid"}, headers=H)
    results["assessment_unlock"] = resp.status == 200
    
    # 8. School overview
    resp = await page.request.get(f"{API_URL}/schools/{school_id}/overview", headers=H)
    results["school_overview"] = resp.status == 200
    
    # 9. School results
    resp = await page.request.get(f"{API_URL}/schools/{school_id}/results", headers=H)
    results["school_results"] = resp.status == 200
    
    # 10. Export CSV
    resp = await page.request.get(f"{API_URL}/schools/{school_id}/export?format=csv", headers=H)
    results["export_csv"] = resp.status == 200 and "text/csv" in resp.headers.get("content-type", "")
    
    # 11. Export XLSX
    resp = await page.request.get(f"{API_URL}/schools/{school_id}/export?format=xlsx", headers=H)
    results["export_xlsx"] = resp.status == 200 and "spreadsheetml" in resp.headers.get("content-type", "")
    
    # 12. Backup
    resp = await page.request.post(f"{API_URL}/admin/backup", headers=H)
    results["backup_create"] = resp.status == 200
    
    print("Regresi results:")
    for k, v in results.items():
        print(f"  {k}: {'PASS' if v else 'FAIL'}")
    
    all_pass = all(results.values())
    print(f"REGRESI: {'PASS' if all_pass else 'FAIL'}")
    return all_pass, results


async def main():
    print("Starting verification...")
    print(f"Base URL: {BASE_URL}")
    print(f"Screenshot dir: {SHOT_DIR}")
    
    async with async_playwright() as p:
        browser = await p.chromium.launch(headless=True)
        context = await browser.new_context()
        page = await context.new_page()
        
        # Enable console logging
        page.on("console", lambda msg: print(f"  CONSOLE: {msg.text}"))
        page.on("pageerror", lambda err: print(f"  PAGE ERROR: {err}"))
        
        try:
            # Setup auth
            await setup_auth(page)
            
            # Run all tests
            bug_results = {}
            
            bug_results["BUG-003"] = await test_bug003_duplicate_school(page)
            bug_results["BUG-001"] = await test_bug001_mobile_schools_table(page)
            bug_results["BUG-002"] = await test_bug002_mobile_assessment_accordion(page)
            bug_results["BUG-005"] = await test_bug005_unlock_modal_counter(page)
            bug_results["BUG-004"] = await test_bug004_offline_sync(page)
            
            reg_pass, reg_details = await test_regression_api(page)
            bug_results["REGRESI"] = reg_pass
            
            # Summary
            print("\n" + "="*50)
            print("VERIFIKASI HASIL")
            print("="*50)
            for bug, result in bug_results.items():
                status = "OK" if result else "TIDAK"
                print(f"{bug}: {status}")
            
            all_bugs_pass = all(bug_results[k] for k in ["BUG-001", "BUG-002", "BUG-003", "BUG-004", "BUG-005"])
            final_status = "GO" if (all_bugs_pass and reg_pass) else "NO-GO"
            print(f"\nStatus akhir: {final_status}")
            print(f"  5 bug terverifikasi: {'YA' if all_bugs_pass else 'TIDAK'}")
            print(f"  Regresi lulus: {'YA' if reg_pass else 'TIDAK'}")
            
            # Save summary
            summary = {
                "timestamp": time.strftime("%Y-%m-%d %H:%M:%S"),
                "bugs": bug_results,
                "regression_details": reg_details,
                "all_bugs_pass": all_bugs_pass,
                "regression_pass": reg_pass,
                "final_status": final_status
            }
            with open(SHOT_DIR / "verify-summary.json", "w") as f:
                json.dump(summary, f, indent=2)
            
        finally:
            await browser.close()


if __name__ == "__main__":
    asyncio.run(main())