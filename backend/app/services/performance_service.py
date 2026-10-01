import logging
from datetime import date
from sqlalchemy import text
from database import AsyncSessionLocal
from app.domain.history import HistorySyncRequest

logger = logging.getLogger("AlqasemyTrader")

class PerformanceService:
    @staticmethod
    async def process_history_sync(request_data: HistorySyncRequest) -> bool:
        try:
            # فتح جلسة اتصال غير متزامنة مع قاعدة البيانات
            async with AsyncSessionLocal() as db:
                
                # 1. جلب بيانات الحساب
                query_account = text("SELECT id, balance, equity FROM trading_accounts WHERE account_number = :account_number")
                result = await db.execute(query_account, {"account_number": str(request_data.account_number)})
                account = result.fetchone()
                    
                if not account:
                    logger.error(f"Account {request_data.account_number} not found.")
                    return False

                account_id = account[0]
                current_balance = float(account[1])
                current_equity = float(account[2])
                
                # 2. تحديد تاريخ اليوم
                today = date.today().isoformat()
                
                trades_closed = len(request_data.deals)
                if trades_closed == 0:
                    return True # لا توجد صفقات اليوم
                    
                # 3. متغيرات الحساب
                trades_won = 0
                trades_lost = 0
                trades_breakeven = 0
                gross_profit = 0.0
                gross_loss = 0.0
                total_realized_pnl = 0.0
                total_commission = 0.0
                total_swap = 0.0
                largest_win = 0.0
                largest_loss = 0.0

                # 4. تحليل الصفقات
                for deal in request_data.deals:
                    net_profit = deal.profit + deal.commission + deal.swap
                    total_realized_pnl += net_profit
                    total_commission += deal.commission
                    total_swap += deal.swap
                    
                    if net_profit > 0:
                        trades_won += 1
                        gross_profit += net_profit
                        if net_profit > largest_win:
                            largest_win = net_profit
                    elif net_profit < 0:
                        trades_lost += 1
                        gross_loss += abs(net_profit)
                        if net_profit < largest_loss:
                            largest_loss = net_profit
                    else:
                        trades_breakeven += 1

                # 5. حساب الإحصائيات المعقدة
                win_rate = (trades_won / trades_closed) * 100 if trades_closed > 0 else 0.0
                profit_factor = (gross_profit / gross_loss) if gross_loss > 0 else (gross_profit if gross_profit > 0 else 0)
                average_win = (gross_profit / trades_won) if trades_won > 0 else 0.0
                average_loss = (gross_loss / trades_lost) if trades_lost > 0 else 0.0
                average_trade = (total_realized_pnl / trades_closed) if trades_closed > 0 else 0.0

                # 6. التحقق من وجود سجل لليوم
                query_check = text("SELECT id FROM performance_daily WHERE account_id = :account_id AND date = :date")
                check_result = await db.execute(query_check, {"account_id": account_id, "date": today})
                existing_perf = check_result.fetchone()

                # 7. التحديث أو الإدراج (Upsert) باستخدام SQLAlchemy
                if existing_perf:
                    record_id = existing_perf[0]
                    query_update = text("""
                        UPDATE performance_daily 
                        SET ending_balance = :ending_balance, ending_equity = :ending_equity, realized_pnl = :realized_pnl,
                            commission_total = :commission_total, swap_total = :swap_total, trades_closed = :trades_closed,
                            trades_won = :trades_won, trades_lost = :trades_lost, trades_breakeven = :trades_breakeven,
                            win_rate = :win_rate, profit_factor = :profit_factor, largest_win = :largest_win,
                            largest_loss = :largest_loss, average_win = :average_win, average_loss = :average_loss,
                            average_trade = :average_trade, updated_at = now()
                        WHERE id = :id
                    """)
                    await db.execute(query_update, {
                        "ending_balance": current_balance, "ending_equity": current_equity, "realized_pnl": total_realized_pnl,
                        "commission_total": total_commission, "swap_total": total_swap, "trades_closed": trades_closed,
                        "trades_won": trades_won, "trades_lost": trades_lost, "trades_breakeven": trades_breakeven,
                        "win_rate": round(win_rate, 2), "profit_factor": round(profit_factor, 2), "largest_win": round(largest_win, 2),
                        "largest_loss": round(largest_loss, 2), "average_win": round(average_win, 2), "average_loss": round(average_loss, 2),
                        "average_trade": round(average_trade, 2), "id": record_id
                    })
                else:
                    query_insert = text("""
                        INSERT INTO performance_daily (
                            account_id, date, starting_balance, ending_balance, starting_equity, ending_equity,
                            realized_pnl, commission_total, swap_total, trades_closed, trades_won, trades_lost,
                            trades_breakeven, win_rate, profit_factor, largest_win, largest_loss, average_win,
                            average_loss, average_trade
                        ) VALUES (
                            :account_id, :date, :starting_balance, :ending_balance, :starting_equity, :ending_equity,
                            :realized_pnl, :commission_total, :swap_total, :trades_closed, :trades_won, :trades_lost,
                            :trades_breakeven, :win_rate, :profit_factor, :largest_win, :largest_loss, :average_win,
                            :average_loss, :average_trade
                        )
                    """)
                    await db.execute(query_insert, {
                        "account_id": account_id, "date": today,
                        "starting_balance": current_balance - total_realized_pnl, "ending_balance": current_balance,
                        "starting_equity": current_equity - total_realized_pnl, "ending_equity": current_equity,
                        "realized_pnl": total_realized_pnl, "commission_total": total_commission, "swap_total": total_swap,
                        "trades_closed": trades_closed, "trades_won": trades_won, "trades_lost": trades_lost,
                        "trades_breakeven": trades_breakeven, "win_rate": round(win_rate, 2), "profit_factor": round(profit_factor, 2),
                        "largest_win": round(largest_win, 2), "largest_loss": round(largest_loss, 2), "average_win": round(average_win, 2),
                        "average_loss": round(average_loss, 2), "average_trade": round(average_trade, 2)
                    })
                
                # حفظ التغييرات في قاعدة البيانات
                await db.commit()

            logger.info(f"✅ Performance stats calculated and saved for account {request_data.account_number}")
            return True
            
        except Exception as e:
            logger.error(f"❌ Error processing history sync: {str(e)}")
            return False
