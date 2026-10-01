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
                query_account = text("""
                    SELECT id, balance, equity 
                    FROM trading_accounts 
                    WHERE account_number = :account_number
                """)
                result = await db.execute(query_account, {"account_number": str(request_data.account_number)})
                account = result.fetchone()
                    
                if not account:
                    logger.error(f"Account {request_data.account_number} not found.")
                    return False

                account_id = str(account[0])
                current_balance = float(account[1] or 0.0)
                current_equity = float(account[2] or 0.0)
                
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

                # 4. تحليل وحفظ الصفقات
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

                    # حفظ الصفقة الفردية في جدول trade_history لتظهر في التطبيق
                    query_check_deal = text("SELECT deal_ticket FROM trade_history WHERE deal_ticket = :deal_ticket")
                    deal_exists = await db.execute(query_check_deal, {"deal_ticket": deal.deal_ticket})
                    
                    if not deal_exists.fetchone():
                        query_insert_deal = text("""
                            INSERT INTO trade_history (
                                deal_ticket, order_ticket, position_ticket, account_number, symbol, side,
                                volume, open_price, close_price, sl, tp, profit, commission, swap, magic,
                                comment, open_time, close_time, created_at
                            ) VALUES (
                                :deal_ticket, :order_ticket, :position_ticket, :account_number, :symbol, :side,
                                :volume, :open_price, :close_price, :sl, :tp, :profit, :commission, :swap, :magic,
                                :comment, :open_time, :close_time, now()
                            )
                        """)
                        await db.execute(query_insert_deal, {
                            "deal_ticket": deal.deal_ticket,
                            "order_ticket": deal.order_ticket,
                            "position_ticket": deal.position_ticket,
                            "account_number": request_data.account_number,
                            "symbol": deal.symbol,
                            "side": deal.side,
                            "volume": deal.volume,
                            "open_price": deal.open_price,
                            "close_price": deal.close_price,
                            "sl": deal.sl,
                            "tp": deal.tp,
                            "profit": deal.profit,
                            "commission": deal.commission,
                            "swap": deal.swap,
                            "magic": request_data.magic,
                            "comment": deal.comment,
                            "open_time": deal.open_time,
                            "close_time": deal.close_time
                        })

                # 5. حساب الإحصائيات المعقدة
                win_rate = (trades_won / trades_closed) * 100 if trades_closed > 0 else 0.0
                profit_factor = (gross_profit / gross_loss) if gross_loss > 0 else (gross_profit if gross_profit > 0 else 0.0)
                average_win = (gross_profit / trades_won) if trades_won > 0 else 0.0
                average_loss = (gross_loss / trades_lost) if trades_lost > 0 else 0.0
                average_trade = (total_realized_pnl / trades_closed) if trades_closed > 0 else 0.0

                # 6. تحديث جدول الأداء (Upsert) بطريقة آمنة ومتوافقة مع PostgreSQL
                query_upsert = text("""
                    INSERT INTO performance_daily (
                        account_id, date, starting_balance, ending_balance, starting_equity, ending_equity,
                        realized_pnl, commission_total, swap_total, trades_closed, trades_won, trades_lost,
                        trades_breakeven, win_rate, profit_factor, largest_win, largest_loss, average_win,
                        average_loss, average_trade, updated_at
                    ) VALUES (
                        CAST(:account_id AS uuid), CAST(:date AS date), :starting_balance, :ending_balance, 
                        :starting_equity, :ending_equity, :realized_pnl, :commission_total, :swap_total, 
                        :trades_closed, :trades_won, :trades_lost, :trades_breakeven, :win_rate, 
                        :profit_factor, :largest_win, :largest_loss, :average_win, :average_loss, 
                        :average_trade, now()
                    )
                    ON CONFLICT (account_id, date) 
                    DO UPDATE SET
                        ending_balance = EXCLUDED.ending_balance,
                        ending_equity = EXCLUDED.ending_equity,
                        realized_pnl = EXCLUDED.realized_pnl,
                        commission_total = EXCLUDED.commission_total,
                        swap_total = EXCLUDED.swap_total,
                        trades_closed = EXCLUDED.trades_closed,
                        trades_won = EXCLUDED.trades_won,
                        trades_lost = EXCLUDED.trades_lost,
                        trades_breakeven = EXCLUDED.trades_breakeven,
                        win_rate = EXCLUDED.win_rate,
                        profit_factor = EXCLUDED.profit_factor,
                        largest_win = EXCLUDED.largest_win,
                        largest_loss = EXCLUDED.largest_loss,
                        average_win = EXCLUDED.average_win,
                        average_loss = EXCLUDED.average_loss,
                        average_trade = EXCLUDED.average_trade,
                        updated_at = now()
                """)

                await db.execute(query_upsert, {
                    "account_id": account_id,
                    "date": today,
                    "starting_balance": current_balance - total_realized_pnl,
                    "ending_balance": current_balance,
                    "starting_equity": current_equity - total_realized_pnl,
                    "ending_equity": current_equity,
                    "realized_pnl": total_realized_pnl,
                    "commission_total": total_commission,
                    "swap_total": total_swap,
                    "trades_closed": trades_closed,
                    "trades_won": trades_won,
                    "trades_lost": trades_lost,
                    "trades_breakeven": trades_breakeven,
                    "win_rate": round(win_rate, 2),
                    "profit_factor": round(profit_factor, 2),
                    "largest_win": round(largest_win, 2),
                    "largest_loss": round(largest_loss, 2),
                    "average_win": round(average_win, 2),
                    "average_loss": round(average_loss, 2),
                    "average_trade": round(average_trade, 2)
                })
                
                # حفظ التغييرات في قاعدة البيانات
                await db.commit()

            logger.info(f"✅ Performance and {trades_closed} trades successfully synced for account {request_data.account_number}")
            return True
            
        except Exception as e:
            logger.error(f"❌ Error processing history sync: {str(e)}")
            return False
