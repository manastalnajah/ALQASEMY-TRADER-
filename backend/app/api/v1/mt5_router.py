@router.post("/account/sync")
async def sync_account(account_data: AccountHeartbeat, x_mt5_key: str | None = Header(default=None)):
    _authorize(x_mt5_key)
    db = SessionLocal()
    try:
        margin_level = account_data.margin_level if account_data.margin_level is not None else (
            account_data.equity / account_data.margin * 100 if account_data.margin > 0 else 0
        )
        server_name = account_data.server or "unknown"

        # 1. تحديث الحساب المسجل مسبقاً بناءً على رقم الحساب account_number
        result = db.execute(text("""
            UPDATE trading_accounts 
            SET balance = CAST(:balance AS NUMERIC),
                equity = CAST(:equity AS NUMERIC),
                margin = CAST(:margin AS NUMERIC),
                free_margin = CAST(:free_margin AS NUMERIC),
                profit = CAST(:profit AS NUMERIC),
                margin_level = CAST(:margin_level AS NUMERIC),
                is_connected = :connected,
                is_active = true,
                server = CASE WHEN server IS NULL OR server = '' OR server = 'unknown' THEN :server ELSE server END,
                currency = COALESCE(:currency, currency),
                leverage = COALESCE(:leverage, leverage),
                ea_id = COALESCE(NULLIF(:ea_id, ''), ea_id),
                ea_version = COALESCE(NULLIF(:ea_version, ''), ea_version),
                last_sync = NOW(),
                last_heartbeat = NOW(),
                updated_at = NOW()
            WHERE account_number = CAST(:account AS BIGINT)
            RETURNING id
        """), {
            "balance": account_data.balance,
            "equity": account_data.equity,
            "margin": account_data.margin,
            "free_margin": account_data.free_margin,
            "profit": account_data.profit,
            "margin_level": margin_level,
            "connected": account_data.is_connected,
            "server": server_name,
            "currency": account_data.currency,
            "leverage": account_data.leverage,
            "ea_id": account_data.ea_id or "",
            "ea_version": account_data.ea_version or "",
            "account": account_data.account_number,
        }).first()
                
        # 2. إذا لم يكن الحساب مضافاً أصلاً في جدول trading_accounts، ننشئه كحساب جديد
        if not result:
            db.execute(text("""
                INSERT INTO trading_accounts(
                    account_number, server, balance, equity, margin, free_margin, 
                    profit, margin_level, is_connected, is_active, is_trade_allowed,
                    currency, leverage, ea_id, ea_version, last_sync, last_heartbeat, created_at, updated_at
                )
                VALUES(
                    CAST(:account AS BIGINT), :server, CAST(:balance AS NUMERIC), CAST(:equity AS NUMERIC), 
                    CAST(:margin AS NUMERIC), CAST(:free_margin AS NUMERIC), CAST(:profit AS NUMERIC), 
                    CAST(:margin_level AS NUMERIC), :connected, true, true,
                    COALESCE(:currency, 'USD'), COALESCE(:leverage, 500), :ea_id, :ea_version,
                    NOW(), NOW(), NOW(), NOW()
                )
                ON CONFLICT (account_number) DO UPDATE SET
                    balance = EXCLUDED.balance,
                    equity = EXCLUDED.equity,
                    margin = EXCLUDED.margin,
                    free_margin = EXCLUDED.free_margin,
                    profit = EXCLUDED.profit,
                    margin_level = EXCLUDED.margin_level,
                    is_connected = EXCLUDED.is_connected,
                    last_sync = NOW(),
                    last_heartbeat = NOW(),
                    updated_at = NOW()
            """), {
                "account": account_data.account_number,
                "server": server_name,
                "balance": account_data.balance,
                "equity": account_data.equity,
                "margin": account_data.margin,
                "free_margin": account_data.free_margin,
                "profit": account_data.profit,
                "margin_level": margin_level,
                "connected": account_data.is_connected,
                "currency": account_data.currency,
                "leverage": account_data.leverage,
                "ea_id": account_data.ea_id or "",
                "ea_version": account_data.ea_version or ""
            })
            
        db.commit()
        return {"status": "success", "account_number": account_data.account_number}
        
    except Exception as exc:
        db.rollback()
        logger.exception("Account sync failed: %s", exc)
        raise HTTPException(500, "Account synchronization failed")
    finally:
        db.close()


@router.post("/heartbeat")
async def account_heartbeat(account_data: AccountHeartbeat, x_mt5_key: str | None = Header(default=None)):
    _authorize(x_mt5_key)
    db = SessionLocal()
    try:
        margin_level = account_data.margin_level if account_data.margin_level is not None else (
            account_data.equity / account_data.margin * 100 if account_data.margin > 0 else 0
        )
        db.execute(text("""
            UPDATE trading_accounts 
            SET balance = CAST(:balance AS NUMERIC),
                equity = CAST(:equity AS NUMERIC),
                margin = CAST(:margin AS NUMERIC),
                free_margin = CAST(:free_margin AS NUMERIC),
                profit = CAST(:profit AS NUMERIC),
                margin_level = CAST(:margin_level AS NUMERIC),
                is_connected = :connected,
                is_active = true,
                ea_id = COALESCE(NULLIF(:ea_id, ''), ea_id),
                ea_version = COALESCE(NULLIF(:ea_version, ''), ea_version),
                last_heartbeat = NOW(),
                last_sync = NOW(),
                updated_at = NOW()
            WHERE account_number = CAST(:account AS BIGINT)
        """), {
            "balance": account_data.balance,
            "equity": account_data.equity,
            "margin": account_data.margin,
            "free_margin": account_data.free_margin,
            "profit": account_data.profit,
            "margin_level": margin_level,
            "connected": account_data.is_connected,
            "ea_id": account_data.ea_id or "",
            "ea_version": account_data.ea_version or "",
            "account": account_data.account_number
        })
        db.commit()
        return {"status": "success", "account_number": account_data.account_number}
    except Exception as exc:
        db.rollback()
        logger.exception("Heartbeat failed: %s", exc)
        raise HTTPException(500, "Heartbeat failed")
    finally:
        db.close()
