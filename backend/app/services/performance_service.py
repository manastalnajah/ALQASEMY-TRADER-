from datetime import date
from app.db.supabase import get_supabase_client
from app.logging.logger import system_logger
from app.schemas.history import HistorySyncRequest

class PerformanceService:
    @staticmethod
    async def process_history_sync(request_data: HistorySyncRequest):
        try:
            supabase = get_supabase_client()
            
            # 1. جلب ID الحساب من قاعدة البيانات باستخدام رقم الحساب
            account_resp = supabase.table("trading_accounts")\
                .select("id, balance, equity")\
                .eq("account_number", str(request_data.account_number))\
                .execute()
                
            if not account_resp.data:
                system_logger.error(f"Account {request_data.account_number} not found.")
                return False

            account_id = account_resp.data[0]["id"]
            current_balance = float(account_resp.data[0].get("balance", 0))
            current_equity = float(account_resp.data[0].get("equity", 0))
            
            # 2. تحديد تاريخ اليوم (لأن الأداء يُحسب يومياً)
            today = date.today().isoformat()
            
            # 3. إعداد متغيرات الحساب
            trades_closed = len(request_data.deals)
            if trades_closed == 0:
                return True # لا توجد صفقات مغلقة لمعالجتها
                
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

            # 4. المرور على جميع الصفقات لجمع الإحصائيات
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
                    if net_profit < largest_loss: # الرقم بالسالب
                        largest_loss = net_profit
                else:
                    trades_breakeven += 1

            # 5. حساب المعدلات (Win Rate & Profit Factor)
            win_rate = (trades_won / trades_closed) * 100 if trades_closed > 0 else 0.0
            profit_factor = (gross_profit / gross_loss) if gross_loss > 0 else (gross_profit if gross_profit > 0 else 0)
            
            average_win = (gross_profit / trades_won) if trades_won > 0 else 0.0
            average_loss = (gross_loss / trades_lost) if trades_lost > 0 else 0.0
            average_trade = (total_realized_pnl / trades_closed) if trades_closed > 0 else 0.0

            # 6. تجهيز البيانات للإدراج أو التحديث (Upsert) في Supabase
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

            # جلب السجل الحالي لهذا اليوم لتجنب مسح starting_balance
            existing_perf = supabase.table("performance_daily")\
                .select("id, starting_balance, starting_equity")\
                .eq("account_id", account_id)\
                .eq("date", today)\
                .execute()

            if existing_perf.data:
                # تحديث السجل الموجود
                record_id = existing_perf.data[0]["id"]
                supabase.table("performance_daily").update(performance_data).eq("id", record_id).execute()
            else:
                # إنشاء سجل جديد لليوم
                performance_data["starting_balance"] = current_balance - total_realized_pnl
                performance_data["starting_equity"] = current_equity - total_realized_pnl
                supabase.table("performance_daily").insert(performance_data).execute()

            system_logger.info(f"✅ Performance stats updated successfully for account {request_data.account_number}")
            return True
            
        except Exception as e:
            system_logger.error(f"❌ Error processing history sync: {str(e)}")
            return False
