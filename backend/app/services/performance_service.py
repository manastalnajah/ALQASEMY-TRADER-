# ============================================================
# app/services/performance_service.py
# خدمة الأداء — تُخزّن الصفقات وتحسب الإحصائيات اليومية
# ------------------------------------------------------------
# الإصلاحات:
# 1. trades_closed يُحسب من trade_history وليس من len(request.deals)
#    (كان يُخزَّن 190 كل يوم بسبب إرسال آخر 30 يوم)
# 2. الأداء اليومي دقيق
# ============================================================

import logging
from datetime import date
import datetime as dt

from sqlalchemy import text

from database import AsyncSessionLocal
from app.domain.history import HistorySyncRequest


logger = logging.getLogger("AlqasemyTrader")


class PerformanceService:

    @staticmethod
    async def process_history_sync(request_data: HistorySyncRequest) -> bool:
        """
        استقبال الصفقات من EA:
        1. إدخالها في trade_history (بدون تكرار).
        2. حساب الإحصائيات اليومية من trade_history الفعلي.
        3. تخزين الإحصائيات في performance_daily.
        """
        try:
            async with AsyncSessionLocal() as db:

                # --------------------------------------------------------
                # 1. جلب بيانات الحساب
                # --------------------------------------------------------
                query_account = text("""
                    SELECT id, balance, equity
                    FROM trading_accounts
                    WHERE account_number = :account_number
                """)
                result = await db.execute(
                    query_account,
                    {"account_number": int(request_data.account_number)},
                )
                account = result.fetchone()

                if not account:
                    logger.error(
                        f"Account {request_data.account_number} not found."
                    )
                    return False

                account_id = str(account[0])
                current_balance = float(account[1] or 0.0)
                current_equity = float(account[2] or 0.0)

                today = date.today()

                # --------------------------------------------------------
                # 2. إدخال الصفقات في trade_history (بدون حساب إحصائيات)
                # --------------------------------------------------------
                deals_to_insert = []

                for deal in request_data.deals:
                    open_dt = None
                    close_dt = None
                    try:
                        if deal.open_time:
                            open_dt = dt.datetime.fromtimestamp(
                                int(deal.open_time)
                            )
                        if deal.close_time:
                            close_dt = dt.datetime.fromtimestamp(
                                int(deal.close_time)
                            )
                    except Exception as dt_error:
                        logger.error(
                            f"Error parsing date for deal "
                            f"{deal.deal_ticket}: {dt_error}"
                        )

                    deals_to_insert.append({
                        "deal_ticket": deal.deal_ticket,
                        "order_ticket": deal.order_ticket,
                        "position_ticket": deal.position_ticket,
                        "account_number": int(request_data.account_number),
                        "symbol": deal.symbol,
                        "side": deal.side,
                        "volume": float(deal.volume),
                        "open_price": float(deal.open_price),
                        "close_price": float(deal.close_price),
                        "sl": float(deal.sl),
                        "tp": float(deal.tp),
                        "profit": float(deal.profit),
                        "commission": float(deal.commission),
                        "swap": float(deal.swap),
                        "magic": request_data.magic,
                        "comment": deal.comment or "",
                        "open_time": open_dt,
                        "close_time": close_dt,
                    })

                if deals_to_insert:
                    query_bulk_insert = text("""
                        INSERT INTO trade_history (
                            deal_ticket, order_ticket, position_ticket,
                            account_number, symbol, side,
                            volume, open_price, close_price, sl, tp,
                            profit, commission, swap, magic,
                            comment, open_time, close_time, created_at
                        ) VALUES (
                            :deal_ticket, :order_ticket, :position_ticket,
                            :account_number, :symbol, :side,
                            :volume, :open_price, :close_price, :sl, :tp,
                            :profit, :commission, :swap, :magic,
                            :comment, :open_time, :close_time, now()
                        )
                        ON CONFLICT (deal_ticket) DO NOTHING
                    """)
                    await db.execute(query_bulk_insert, deals_to_insert)

                # --------------------------------------------------------
                # 3. ✅ الإصلاح: احسب الإحصائيات من trade_history الفعلي
                #    (بدلًا من len(request_data.deals) الذي كان يُخزّن
                #     آخر 190 صفقة كل يوم)
                # --------------------------------------------------------
                count_query = text("""
                    SELECT
                        COUNT(*) AS total,
                        SUM(CASE WHEN (profit + commission + swap) > 0
                                 THEN 1 ELSE 0 END) AS wins,
                        SUM(CASE WHEN (profit + commission + swap) < 0
                                 THEN 1 ELSE 0 END) AS losses,
                        SUM(CASE WHEN (profit + commission + swap) = 0
                                 THEN 1 ELSE 0 END) AS breakevens,
                        COALESCE(SUM(profit + commission + swap), 0) AS total_pnl,
                        COALESCE(SUM(CASE
                            WHEN (profit + commission + swap) > 0
                            THEN (profit + commission + swap) ELSE 0 END), 0)
                            AS gross_profit,
                        COALESCE(SUM(CASE
                            WHEN (profit + commission + swap) < 0
                            THEN ABS(profit + commission + swap) ELSE 0 END), 0)
                            AS gross_loss,
                        COALESCE(MAX(profit + commission + swap), 0)
                            AS largest_win,
                        COALESCE(MIN(profit + commission + swap), 0)
                            AS largest_loss,
                        COALESCE(SUM(commission), 0) AS commission_total,
                        COALESCE(SUM(swap), 0) AS swap_total
                    FROM trade_history
                    WHERE account_number = :acc_num
                      AND DATE(close_time) = :today
                """)

                count_result = (await db.execute(count_query, {
                    "acc_num": int(request_data.account_number),
                    "today": today,
                })).mappings().first()

                trades_closed    = int(count_result["total"] or 0)
                trades_won       = int(count_result["wins"] or 0)
                trades_lost      = int(count_result["losses"] or 0)
                trades_breakeven = int(count_result["breakevens"] or 0)

                total_realized_pnl = float(count_result["total_pnl"] or 0.0)
                gross_profit       = float(count_result["gross_profit"] or 0.0)
                gross_loss         = float(count_result["gross_loss"] or 0.0)
                largest_win        = float(count_result["largest_win"] or 0.0)
                largest_loss       = float(count_result["largest_loss"] or 0.0)
                total_commission   = float(count_result["commission_total"] or 0.0)
                total_swap         = float(count_result["swap_total"] or 0.0)

                # إذا لا صفقات اليوم، لا نحفظ شيئًا
                if trades_closed == 0:
                    await db.commit()
                    logger.info(
                        f"No closed trades today for account "
                        f"{request_data.account_number}"
                    )
                    return True

                # --------------------------------------------------------
                # 4. حساب الإحصائيات النهائية
                # --------------------------------------------------------
                win_rate = (
                    (trades_won / trades_closed) * 100
                    if trades_closed > 0 else 0.0
                )
                profit_factor = (
                    (gross_profit / gross_loss) if gross_loss > 0
                    else (gross_profit if gross_profit > 0 else 0.0)
                )
                average_win = (
                    (gross_profit / trades_won) if trades_won > 0 else 0.0
                )
                average_loss = (
                    (gross_loss / trades_lost) if trades_lost > 0 else 0.0
                )
                average_trade = (
                    (total_realized_pnl / trades_closed)
                    if trades_closed > 0 else 0.0
                )

                # --------------------------------------------------------
                # 5. Upsert في performance_daily
                # --------------------------------------------------------
                query_upsert = text("""
                    INSERT INTO performance_daily (
                        account_id, date, starting_balance, ending_balance,
                        starting_equity, ending_equity,
                        realized_pnl, commission_total, swap_total,
                        trades_closed, trades_won, trades_lost,
                        trades_breakeven, win_rate, profit_factor,
                        largest_win, largest_loss, average_win,
                        average_loss, average_trade, updated_at
                    ) VALUES (
                        CAST(:account_id AS uuid), CAST(:date AS date),
                        :starting_balance, :ending_balance,
                        :starting_equity, :ending_equity,
                        :realized_pnl, :commission_total, :swap_total,
                        :trades_closed, :trades_won, :trades_lost,
                        :trades_breakeven, :win_rate, :profit_factor,
                        :largest_win, :largest_loss, :average_win,
                        :average_loss, :average_trade, now()
                    )
                    ON CONFLICT (account_id, date)
                    DO UPDATE SET
                        ending_balance    = EXCLUDED.ending_balance,
                        ending_equity     = EXCLUDED.ending_equity,
                        realized_pnl      = EXCLUDED.realized_pnl,
                        commission_total  = EXCLUDED.commission_total,
                        swap_total        = EXCLUDED.swap_total,
                        trades_closed     = EXCLUDED.trades_closed,
                        trades_won        = EXCLUDED.trades_won,
                        trades_lost       = EXCLUDED.trades_lost,
                        trades_breakeven  = EXCLUDED.trades_breakeven,
                        win_rate          = EXCLUDED.win_rate,
                        profit_factor     = EXCLUDED.profit_factor,
                        largest_win       = EXCLUDED.largest_win,
                        largest_loss      = EXCLUDED.largest_loss,
                        average_win       = EXCLUDED.average_win,
                        average_loss      = EXCLUDED.average_loss,
                        average_trade     = EXCLUDED.average_trade,
                        updated_at        = now()
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
                    "average_trade": round(average_trade, 2),
                })

                await db.commit()

            logger.info(
                f"✅ Performance and {trades_closed} trades successfully "
                f"synced for account {request_data.account_number}"
            )
            return True

        except Exception as e:
            logger.error(f"❌ Error processing history sync: {str(e)}")
            return False

    # =========================================================================
    # دالة جلب بيانات الأداء ومنحنى الرصيد لتطبيق فلاتر
    # =========================================================================
    @staticmethod
    async def get_performance_data(account_id: str) -> dict:
        try:
            async with AsyncSessionLocal() as db:

                # 1. الإحصائيات العامة
                stats_query = text("""
                    SELECT
                        COALESCE(SUM(realized_pnl), 0) AS total_profit,
                        COALESCE(SUM(trades_closed), 0) AS total_trades,
                        COALESCE(SUM(trades_won), 0) AS winning_trades,
                        COALESCE(SUM(trades_lost), 0) AS losing_trades,
                        COALESCE(SUM(average_win * trades_won), 0)
                            AS gross_profit,
                        COALESCE(SUM(average_loss * trades_lost), 0)
                            AS gross_loss,
                        MAX(largest_win) AS largest_win,
                        MIN(largest_loss) AS largest_loss
                    FROM performance_daily
                    WHERE account_id = CAST(:acc_id AS UUID)
                """)
                stats_result = (await db.execute(
                    stats_query, {"acc_id": account_id}
                )).mappings().first()

                stats = {}
                if stats_result and stats_result["total_trades"] > 0:
                    t_won = int(stats_result["winning_trades"])
                    t_closed = int(stats_result["total_trades"])
                    win_rate = (
                        (t_won / t_closed) * 100 if t_closed > 0 else 0.0
                    )

                    gross_loss = float(stats_result["gross_loss"])
                    gross_profit = float(stats_result["gross_profit"])
                    profit_factor = (
                        (gross_profit / gross_loss) if gross_loss > 0
                        else (gross_profit if gross_profit > 0 else 0.0)
                    )

                    stats = {
                        "totalProfit": float(stats_result["total_profit"]),
                        "totalTrades": t_closed,
                        "winningTrades": t_won,
                        "losingTrades": int(stats_result["losing_trades"]),
                        "winRate": round(win_rate, 2),
                        "profitFactor": round(profit_factor, 2),
                        "largestWin": float(stats_result["largest_win"] or 0.0),
                        "largestLoss": float(stats_result["largest_loss"] or 0.0),
                    }

                # 2. منحنى الرصيد
                curve_query = text("""
                    SELECT date, ending_equity AS equity
                    FROM performance_daily
                    WHERE account_id = CAST(:acc_id AS UUID)
                    ORDER BY date ASC
                """)
                curve_result = (await db.execute(
                    curve_query, {"acc_id": account_id}
                )).mappings().all()

                equity_curve = [
                    {
                        "date": str(row["date"]),
                        "equity": float(row["equity"] or 0.0),
                    }
                    for row in curve_result
                ]

                # 3. الأداء الشهري
                monthly_query = text("""
                    SELECT
                        TO_CHAR(date, 'Mon YYYY') AS month,
                        SUM(realized_pnl) AS profit
                    FROM performance_daily
                    WHERE account_id = CAST(:acc_id AS UUID)
                    GROUP BY
                        TO_CHAR(date, 'Mon YYYY'),
                        EXTRACT(YEAR FROM date),
                        EXTRACT(MONTH FROM date)
                    ORDER BY
                        EXTRACT(YEAR FROM date),
                        EXTRACT(MONTH FROM date)
                """)
                monthly_result = (await db.execute(
                    monthly_query, {"acc_id": account_id}
                )).mappings().all()

                monthly_performance = [
                    {
                        "month": row["month"],
                        "profit": float(row["profit"] or 0.0),
                    }
                    for row in monthly_result
                ]

                return {
                    "status": "success",
                    "stats": stats,
                    "equityCurve": equity_curve,
                    "monthlyPerformance": monthly_performance,
                }

        except Exception as e:
            logger.error(
                f"Error fetching performance data for account "
                f"{account_id}: {str(e)}"
            )
            return {"status": "error", "message": str(e)}
