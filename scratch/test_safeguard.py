import sys
from fastapi import HTTPException

# Add workspace root to python path to import server
sys.path.append(".")
from server import delete_jules_session, DeleteSessionInput

def test_delete_active_without_confirm(session_id):
    print(f"Testing delete of active session {session_id} WITHOUT confirm_active_delete...")
    try:
        delete_jules_session(DeleteSessionInput(
            session_id=session_id,
            purge_local_cache=False,
            confirm_active_delete=False
        ))
        print("FAIL: Deletion succeeded when it should have been blocked!")
        return False
    except HTTPException as he:
        print(f"SUCCESS: Blocked successfully! Status code: {he.status_code}, Detail: {he.detail}")
        if "WARNING_ACTIVE_SESSION" in he.detail:
            print("Verified: Warning message contains active session safeguard trigger.")
            return True
        else:
            print("FAIL: Unexpected error detail:", he.detail)
            return False
    except Exception as e:
        print("FAIL: Unexpected error type:", e)
        return False

def test_delete_active_with_confirm(session_id):
    print(f"\nTesting delete of active session {session_id} WITH confirm_active_delete...")
    try:
        res = delete_jules_session(DeleteSessionInput(
            session_id=session_id,
            purge_local_cache=False,
            confirm_active_delete=True
        ))
        print("SUCCESS: Deletion succeeded as expected! Result:", res)
        return True
    except Exception as e:
        print("FAIL: Deletion failed when it should have succeeded:", e)
        return False

if __name__ == "__main__":
    session_id = "8629302199467347624"
    ok1 = test_delete_active_without_confirm(session_id)
    if not ok1:
        sys.exit(1)
        
    ok2 = test_delete_active_with_confirm(session_id)
    if not ok2:
        sys.exit(1)
        
    print("\nALL SAFEGUARD TESTS PASSED!")
    sys.exit(0)
