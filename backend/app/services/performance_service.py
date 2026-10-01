import logging
from datetime import date
from database import supabase  # تأكد من أن هذا الاستدعاء يطابق طريقة اتصالك بقاعدة البيانات
from app.domain.history import HistorySyncRequest

logger = logging.getLogger("AlqasemyTrader")

class PerformanceService:
    @staticmethod
    async def process_history_sync(request_data: HistorySyncRequest) -> bool:
        try:
            # 1. جلب بيانات الحساب
            account_resp = supabase.table("trading_accounts").select("id, balance, equity").eq("account_number", str(request_data.account_number)).execute()
                
            if not account_resp.data:
                logger.error(f"Account {request_data.account_number} not found.")
                return False

            account_id = account_resp.data[0]["id"]
            current_balance = float(account_resp.data[0].get("balance", 0))
            current_equity = float(account_resp.data[0].get("equity", 0))
            
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

            # 6. تجهيز البيانات للإرسال إلى Supabase
            performance_data = {
                "account_id": account_id,
                "date": today,
                "ending_balance": current_balance,
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
            }

            # 7. التحديث أو الإدراج (Upsert)
            existing_perf = supabase.table("performance_daily").select("id").eq("account_id", account_id).eq("date", today).execute()

            if existing_perf.data:
                record_id = existing_perf.data[0]["id"]
                supabase.table("performance_daily").update(performance_data).eq("id", record_id).execute()
            else:
                performance_data["starting_balance"] = current_balance - total_realized_pnl
                performance_data["starting_equity"] = current_equity - total_realized_pnl
                supabase.table("performance_daily").insert(performance_data).execute()

            logger.info(f"✅ Performance stats calculated and saved for account {request_data.account_number}")
            return True
            
        except Exception as e:
            logger.error(f"❌ Error processing history sync: {str(e)}")
            return False
