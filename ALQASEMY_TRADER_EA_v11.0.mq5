//+------------------------------------------------------------------+
//|                    ALQASEMY_TRADER_EA_v11.0.mq5                  |
//|                    Production Hardened / Rule-Based              |
//+------------------------------------------------------------------+
#property strict
#property version "11.0"

#include <Trade/Trade.mqh>

/*
   ALQASEMY TRADER EA v11.0
   ---------------------------------------------------------------
   Production execution gateway for the rule-based Python backend.

   Design rules:
   - NO AI / ML.
   - Backend Risk Engine is authoritative for lot sizing.
   - EA is the final broker-side safety gate.
   - No duplicate position/pending order per symbol for this Magic.
   - No command is executed without SL + TP.
   - Real Bid/Ask and broker symbol specifications are used.
   - Account, positions and symbol specs are synchronized.
   - Commands are atomically ACKed by the backend before execution.
   - Execution reports use the backend's accepted final states.
   - The EA can manage configured symbols from one chart.
*/

input string BackendURL="https://alqasemy-trader.onrender.com";
input string EAToken="CHANGE_ME";
input string EAId="MT5-ALQASEMY-01";

input string SymbolXAU="XAUUSD";
input string SymbolEUR="EURUSD";
input ENUM_TIMEFRAMES DirectionTimeframe=PERIOD_H1;
input ENUM_TIMEFRAMES ConfirmationTimeframe=PERIOD_M15;
input ENUM_TIMEFRAMES EntryTimeframe=PERIOD_M5;

input int PollSeconds=5;
input int SyncSeconds=15;
input int DirectionCandlesInitial=200;
input int ConfirmationCandlesInitial=300;
input int EntryCandlesInitial=500;
input int CandleRecoveryBatch=1000;
input int CandleRecoveryRoundsPerSync=20;
input int DeviationPoints=20;
input long Magic=2026082801;
input bool AllowTrading=true;

// Final EA-side limits. Backend must use equal or stricter values.
input double MaxRiskPerTradePct=0.50;
input int MaxOpenPositionsTotal=1;
input int MaxOpenPositionsPerSymbol=1;
input int MaxPendingOrdersTotal=1;
input int MaxPendingOrdersPerSymbol=1;
input double MaxSymbolExposureLots=1.00;
input double MaxDailyLossPct=3.00;
input double MaxDrawdownPct=10.00;
input double MinMarginLevelPct=300.0;
input double MaxSpreadPoints=30.0;
input int MinCommandAgeSeconds=0;
input int MaxCommandAgeSeconds=300;

input int BreakevenPoints=200;
input int TrailingStartPoints=300;
input int TrailingStepPoints=150;

CTrade trade;
datetime last_poll=0;
datetime last_sync=0;
datetime last_trade_time_xau=0;
datetime last_trade_time_eur=0;

// ------------------------------------------------------------------
// Basic helpers
// ------------------------------------------------------------------
string Canonical(string sym)
{
   string s=sym;
   StringToUpper(s);
   if(StringFind(s,"XAUUSD")==0) return "XAUUSD";
   if(StringFind(s,"EURUSD")==0) return "EURUSD";
   return s;
}

string BrokerSymbol(string canonical)
{
   if(canonical=="XAUUSD") return SymbolXAU;
   if(canonical=="EURUSD") return SymbolEUR;
   return canonical;
}

string IsoTime(datetime t)
{
   MqlDateTime d;
   TimeToStruct(t,d);
   return StringFormat("%04d-%02d-%02dT%02d:%02d:%02d",d.year,d.mon,d.day,d.hour,d.min,d.sec);
}

string Url()
{
   string u=BackendURL;
   StringTrimLeft(u); StringTrimRight(u);
   while(StringLen(u)>0 && StringGetCharacter(u,StringLen(u)-1)=='/')
      u=StringSubstr(u,0,StringLen(u)-1);
   return u;
}

string EscapeJson(string value)
{
   StringReplace(value,"\\","\\\\");
   StringReplace(value,"\"","\\\"");
   StringReplace(value,"\r","\\r");
   StringReplace(value,"\n","\\n");
   StringReplace(value,"\t","\\t");
   return value;
}

string Headers()
{
   return "Content-Type: application/json\r\nAccept: application/json\r\nX-MT5-Key: "+EAToken+"\r\nUser-Agent: ALQASEMY-MT5-EA/11.0\r\n";
}

bool Http(string method,string endpoint,string body,string &out)
{
   out="";
   char data[];
   char result[];
   string result_headers="";
   int code=-1;
   ResetLastError();

   if(method=="GET")
      code=WebRequest("GET",Url()+endpoint,Headers(),60000,data,result,result_headers);
   else
   {
      ArrayResize(data,0);
      if(body!="")
      {
         int written=StringToCharArray(body,data,0,WHOLE_ARRAY,CP_UTF8);
         if(written>0 && ArraySize(data)>0) ArrayResize(data,ArraySize(data)-1);
      }
      code=WebRequest(method,Url()+endpoint,Headers(),60000,data,result,result_headers);
   }

   if(code<200 || code>=300)
   {
      Print("ALQASEMY HTTP failure | code=",code," | endpoint=",endpoint," | last_error=",GetLastError());
      return false;
   }
   if(ArraySize(result)>0) out=CharArrayToString(result,0,WHOLE_ARRAY,CP_UTF8);
   return true;
}

// ------------------------------------------------------------------
// Minimal JSON readers for flat command objects
// ------------------------------------------------------------------
int SkipJsonSpaces(string j,int p)
{
   while(p<StringLen(j))
   {
      ushort c=StringGetCharacter(j,p);
      if(c!=' ' && c!='\t' && c!='\r' && c!='\n') break;
      p++;
   }
   return p;
}

string JStr(string j,string k)
{
   string q="\""+k+"\"";
   int key_pos=StringFind(j,q);
   if(key_pos<0) return "";
   int colon=StringFind(j,":",key_pos+StringLen(q));
   if(colon<0) return "";
   int p=SkipJsonSpaces(j,colon+1);
   if(p>=StringLen(j) || StringGetCharacter(j,p)!='\"') return "";
   p++;
   string value="";
   bool escaped=false;
   for(int i=p;i<StringLen(j);i++)
   {
      ushort c=StringGetCharacter(j,i);
      if(escaped)
      {
         if(c=='n') value+="\n";
         else if(c=='r') value+="\r";
         else if(c=='t') value+="\t";
         else value+=CharToString((uchar)c);
         escaped=false;
         continue;
      }
      if(c=='\\') { escaped=true; continue; }
      if(c=='\"') return value;
      value+=CharToString((uchar)c);
   }
   return "";
}

double JNum(string j,string k)
{
   string q="\""+k+"\"";
   int key_pos=StringFind(j,q);
   if(key_pos<0) return 0;
   int colon=StringFind(j,":",key_pos+StringLen(q));
   if(colon<0) return 0;
   int p=SkipJsonSpaces(j,colon+1);
   if(p>=StringLen(j)) return 0;
   int e=p;
   while(e<StringLen(j))
   {
      ushort c=StringGetCharacter(j,e);
      if(c==',' || c=='}' || c==']' || c==' ' || c=='\t' || c=='\r' || c=='\n') break;
      e++;
   }
   if(e<=p) return 0;
   return StringToDouble(StringSubstr(j,p,e-p));
}

// ------------------------------------------------------------------
// Reports
// ------------------------------------------------------------------
void Report(string command_id,string status,ulong order_ticket,ulong deal_ticket,string message,double fill_price)
{
   if(command_id=="") return;
   string out;
   string body=StringFormat(
      "{\"status\":\"%s\",\"mt5_order_ticket\":%I64d,\"mt5_deal_ticket\":%I64d,\"fill_price\":%.10f,\"message\":\"%s\",\"ea_id\":\"%s\"}",
      EscapeJson(status),(long)order_ticket,(long)deal_ticket,fill_price,EscapeJson(message),EscapeJson(EAId));
   Http("POST","/api/v1/mt5/commands/"+command_id+"/report",body,out);
}

// ------------------------------------------------------------------
// Exposure / duplicate guards
// ------------------------------------------------------------------
int OurOpenPositionsTotal()
{
   int count=0;
   for(int i=PositionsTotal()-1;i>=0;i--)
   {
      ulong ticket=PositionGetTicket(i);
      if(ticket==0) continue;
      if((long)PositionGetInteger(POSITION_MAGIC)==Magic) count++;
   }
   return count;
}

int OurOpenPositionsForSymbol(string symbol)
{
   int count=0;
   for(int i=PositionsTotal()-1;i>=0;i--)
   {
      ulong ticket=PositionGetTicket(i);
      if(ticket==0) continue;
      if((long)PositionGetInteger(POSITION_MAGIC)!=Magic) continue;
      if(PositionGetString(POSITION_SYMBOL)==symbol) count++;
   }
   return count;
}

int OurPendingTotal()
{
   int count=0;
   for(int i=OrdersTotal()-1;i>=0;i--)
   {
      ulong ticket=OrderGetTicket(i);
      if(ticket==0) continue;
      if((long)OrderGetInteger(ORDER_MAGIC)!=Magic) continue;
      ENUM_ORDER_TYPE type=(ENUM_ORDER_TYPE)OrderGetInteger(ORDER_TYPE);
      if(type==ORDER_TYPE_BUY_LIMIT || type==ORDER_TYPE_SELL_LIMIT || type==ORDER_TYPE_BUY_STOP || type==ORDER_TYPE_SELL_STOP)
         count++;
   }
   return count;
}

int OurPendingForSymbol(string symbol)
{
   int count=0;
   for(int i=OrdersTotal()-1;i>=0;i--)
   {
      ulong ticket=OrderGetTicket(i);
      if(ticket==0) continue;
      if((long)OrderGetInteger(ORDER_MAGIC)!=Magic) continue;
      if(OrderGetString(ORDER_SYMBOL)!=symbol) continue;
      ENUM_ORDER_TYPE type=(ENUM_ORDER_TYPE)OrderGetInteger(ORDER_TYPE);
      if(type==ORDER_TYPE_BUY_LIMIT || type==ORDER_TYPE_SELL_LIMIT || type==ORDER_TYPE_BUY_STOP || type==ORDER_TYPE_SELL_STOP)
         count++;
   }
   return count;
}

double OurExposureForSymbol(string symbol)
{
   double total=0.0;
   for(int i=PositionsTotal()-1;i>=0;i--)
   {
      ulong ticket=PositionGetTicket(i);
      if(ticket==0) continue;
      if((long)PositionGetInteger(POSITION_MAGIC)!=Magic) continue;
      if(PositionGetString(POSITION_SYMBOL)!=symbol) continue;
      total+=PositionGetDouble(POSITION_VOLUME);
   }
   return total;
}

bool HasSamePending(string symbol,string side,double entry)
{
   double tick_size=SymbolInfoDouble(symbol,SYMBOL_TRADE_TICK_SIZE);
   double epsilon=(tick_size>0 ? tick_size*0.5 : SymbolInfoDouble(symbol,SYMBOL_POINT));
   for(int i=OrdersTotal()-1;i>=0;i--)
   {
      ulong ticket=OrderGetTicket(i);
      if(ticket==0) continue;
      if((long)OrderGetInteger(ORDER_MAGIC)!=Magic) continue;
      if(OrderGetString(ORDER_SYMBOL)!=symbol) continue;
      ENUM_ORDER_TYPE type=(ENUM_ORDER_TYPE)OrderGetInteger(ORDER_TYPE);
      if(side=="BUY_LIMIT" && type!=ORDER_TYPE_BUY_LIMIT) continue;
      if(side=="SELL_LIMIT" && type!=ORDER_TYPE_SELL_LIMIT) continue;
      double p=OrderGetDouble(ORDER_PRICE_OPEN);
      if(MathAbs(p-entry)<=epsilon) return true;
   }
   return false;
}

bool HasSamePositionDirection(string symbol,string side)
{
   long wanted=(side=="BUY" ? POSITION_TYPE_BUY : POSITION_TYPE_SELL);
   for(int i=PositionsTotal()-1;i>=0;i--)
   {
      ulong ticket=PositionGetTicket(i);
      if(ticket==0) continue;
      if((long)PositionGetInteger(POSITION_MAGIC)!=Magic) continue;
      if(PositionGetString(POSITION_SYMBOL)!=symbol) continue;
      if(PositionGetInteger(POSITION_TYPE)==wanted) return true;
   }
   return false;
}

// ------------------------------------------------------------------
// Broker validation
// ------------------------------------------------------------------
bool ValidateVolume(string symbol,double volume,string &reason)
{
   reason="";
   double minv=SymbolInfoDouble(symbol,SYMBOL_VOLUME_MIN);
   double maxv=SymbolInfoDouble(symbol,SYMBOL_VOLUME_MAX);
   double step=SymbolInfoDouble(symbol,SYMBOL_VOLUME_STEP);
   if(minv<=0 || maxv<=0 || step<=0) { reason="INVALID_VOLUME_SPEC"; return false; }
   if(volume<minv-1e-9 || volume>maxv+1e-9) { reason="VOLUME_OUT_OF_RANGE"; return false; }
   double steps=volume/step;
   if(MathAbs(steps-MathRound(steps))>1e-6) { reason="VOLUME_STEP_MISMATCH"; return false; }
   return true;
}

bool ValidateProtection(string symbol,string side,double entry,double sl,double tp,string &reason)
{
   reason="";
   if(sl<=0 || tp<=0) { reason="SL_TP_REQUIRED"; return false; }
   if(entry<=0) { reason="ENTRY_REQUIRED"; return false; }

   double point=SymbolInfoDouble(symbol,SYMBOL_POINT);
   int digits=(int)SymbolInfoInteger(symbol,SYMBOL_DIGITS);
   long stops=(long)SymbolInfoInteger(symbol,SYMBOL_TRADE_STOPS_LEVEL);
   long freeze=(long)SymbolInfoInteger(symbol,SYMBOL_TRADE_FREEZE_LEVEL);
   double min_dist=MathMax((double)MathMax(stops,freeze),1.0)*point;

   if(side=="BUY" || side=="BUY_LIMIT")
   {
      if(!(sl<entry && tp>entry)) { reason="INVALID_BUY_PROTECTION"; return false; }
      if(entry-sl<min_dist || tp-entry<min_dist) { reason="BUY_STOPS_TOO_CLOSE"; return false; }
   }
   else if(side=="SELL" || side=="SELL_LIMIT")
   {
      if(!(tp<entry && sl>entry)) { reason="INVALID_SELL_PROTECTION"; return false; }
      if(sl-entry<min_dist || entry-tp<min_dist) { reason="SELL_STOPS_TOO_CLOSE"; return false; }
   }
   else { reason="INVALID_ORDER_TYPE"; return false; }
   return true;
}

bool ValidateMarketConditions(string symbol,string side,string &reason)
{
   reason="";
   if(!SymbolSelect(symbol,true)) { reason="SYMBOL_NOT_AVAILABLE"; return false; }
   MqlTick tick;
   if(!SymbolInfoTick(symbol,tick)) { reason="NO_TICK"; return false; }
   double point=SymbolInfoDouble(symbol,SYMBOL_POINT);
   if(point<=0) { reason="INVALID_POINT"; return false; }
   double spread=(tick.ask-tick.bid)/point;
   if(spread>MaxSpreadPoints) { reason=StringFormat("SPREAD_TOO_HIGH:%.1f",spread); return false; }

   double equity=AccountInfoDouble(ACCOUNT_EQUITY);
   double balance=AccountInfoDouble(ACCOUNT_BALANCE);
   double margin=AccountInfoDouble(ACCOUNT_MARGIN);
   if(equity<=0 || balance<=0) { reason="INVALID_ACCOUNT"; return false; }
   if(margin>0)
   {
      double margin_level=equity/margin*100.0;
      if(margin_level<MinMarginLevelPct) { reason="LOW_MARGIN_LEVEL"; return false; }
   }
   return true;
}

bool ValidateRisk(string symbol,string side,double volume,double entry,double sl,string &reason)
{
   reason="";
   double equity=AccountInfoDouble(ACCOUNT_EQUITY);
   if(equity<=0) { reason="INVALID_EQUITY"; return false; }
   double tick_size=SymbolInfoDouble(symbol,SYMBOL_TRADE_TICK_SIZE);
   double tick_value=SymbolInfoDouble(symbol,SYMBOL_TRADE_TICK_VALUE);
   if(tick_size<=0 || tick_value<=0) { reason="INVALID_TICK_SPEC"; return false; }
   double loss_per_lot=MathAbs(entry-sl)/tick_size*tick_value;
   double estimated_loss=loss_per_lot*volume;
   double max_loss=equity*(MaxRiskPerTradePct/100.0);
   // Small tolerance is allowed for spread/current price movement.
   if(estimated_loss>max_loss*1.05) { reason=StringFormat("EA_RISK_LIMIT:%.2f>%.2f",estimated_loss,max_loss); return false; }
   return true;
}

// ------------------------------------------------------------------
// Execution
// ------------------------------------------------------------------
bool Execute(string command_id,string side,string canonical,double volume,double entry_price,double sl,double tp)
{
   StringToUpper(side);
   canonical=Canonical(canonical);
   string symbol=BrokerSymbol(canonical);
   if(symbol=="") { Report(command_id,"failed",0,0,"SYMBOL_EMPTY",0); return false; }
   if(!SymbolSelect(symbol,true)) { Report(command_id,"failed",0,0,"SYMBOL_NOT_AVAILABLE",0); return false; }
   if(!AllowTrading) { Report(command_id,"ignored",0,0,"TRADING_DISABLED",0); return true; }

   // Final duplicate / exposure gates.
   if(OurOpenPositionsTotal()>=MaxOpenPositionsTotal)
   { Report(command_id,"ignored",0,0,"MAX_OPEN_POSITIONS",0); return true; }
   if(OurOpenPositionsForSymbol(symbol)>=MaxOpenPositionsPerSymbol)
   { Report(command_id,"ignored",0,0,"MAX_OPEN_POSITIONS_SYMBOL",0); return true; }
   if(OurPendingTotal()>=MaxPendingOrdersTotal)
   { Report(command_id,"ignored",0,0,"MAX_PENDING_ORDERS",0); return true; }

   if(side=="BUY" || side=="SELL")
   {
      if(HasSamePositionDirection(symbol,side))
      { Report(command_id,"ignored",0,0,"DUPLICATE_POSITION",0); return true; }
   }
   else if(side=="BUY_LIMIT" || side=="SELL_LIMIT")
   {
      if(OurPendingForSymbol(symbol)>=MaxPendingOrdersPerSymbol)
      { Report(command_id,"ignored",0,0,"MAX_PENDING_ORDERS_SYMBOL",0); return true; }
      if(HasSamePending(symbol,side,entry_price))
      { Report(command_id,"ignored",0,0,"DUPLICATE_PENDING",0); return true; }
   }
   else
   { Report(command_id,"failed",0,0,"INVALID_ORDER_TYPE",0); return false; }

   double symbol_exposure=OurExposureForSymbol(symbol);
   if(symbol_exposure+volume>MaxSymbolExposureLots+1e-9)
   { Report(command_id,"ignored",0,0,"MAX_SYMBOL_EXPOSURE",0); return true; }

   string reason;
   if(!ValidateVolume(symbol,volume,reason)) { Report(command_id,"failed",0,0,reason,0); return false; }
   if(!ValidateMarketConditions(symbol,side,reason)) { Report(command_id,"ignored",0,0,reason,0); return true; }

   MqlTick tick;
   if(!SymbolInfoTick(symbol,tick)) { Report(command_id,"failed",0,0,"NO_TICK",0); return false; }

   double execution_entry=entry_price;
   if(side=="BUY") execution_entry=tick.ask;
   if(side=="SELL") execution_entry=tick.bid;

   int digits=(int)SymbolInfoInteger(symbol,SYMBOL_DIGITS);
   double tick_size=SymbolInfoDouble(symbol,SYMBOL_TRADE_TICK_SIZE);
   if(tick_size<=0) { Report(command_id,"failed",0,0,"INVALID_TICK_SIZE",0); return false; }

   execution_entry=NormalizeDouble(MathRound(execution_entry/tick_size)*tick_size,digits);
   sl=NormalizeDouble(MathRound(sl/tick_size)*tick_size,digits);
   tp=NormalizeDouble(MathRound(tp/tick_size)*tick_size,digits);
   if(side=="BUY_LIMIT" || side=="SELL_LIMIT")
      entry_price=NormalizeDouble(MathRound(entry_price/tick_size)*tick_size,digits);

   // Pending prices are rejected if they are no longer valid; never shift a strategy order.
   if(side=="BUY_LIMIT" && entry_price>=tick.ask) { Report(command_id,"ignored",0,0,"BUY_LIMIT_NO_LONGER_BELOW_ASK",0); return true; }
   if(side=="SELL_LIMIT" && entry_price<=tick.bid) { Report(command_id,"ignored",0,0,"SELL_LIMIT_NO_LONGER_ABOVE_BID",0); return true; }

   double protection_entry=(side=="BUY" || side=="SELL") ? execution_entry : entry_price;
   if(!ValidateProtection(symbol,side,protection_entry,sl,tp,reason))
   { Report(command_id,"failed",0,0,reason,0); return false; }
   if(!ValidateRisk(symbol,side,volume,protection_entry,sl,reason))
   { Report(command_id,"ignored",0,0,reason,0); return true; }

   MqlTradeRequest request;
   MqlTradeResult result;
   ZeroMemory(request);
   ZeroMemory(result);

   request.magic=Magic;
   request.symbol=symbol;
   request.volume=volume;
   request.deviation=DeviationPoints;
   request.sl=sl;
   request.tp=tp;
   request.comment="ALQASEMY|"+EAId;

   int filling=(int)SymbolInfoInteger(symbol,SYMBOL_FILLING_MODE);
   if((filling & SYMBOL_FILLING_FOK)!=0) request.type_filling=ORDER_FILLING_FOK;
   else if((filling & SYMBOL_FILLING_IOC)!=0) request.type_filling=ORDER_FILLING_IOC;
   else request.type_filling=ORDER_FILLING_RETURN;

   if(side=="BUY")
   {
      request.action=TRADE_ACTION_DEAL;
      request.type=ORDER_TYPE_BUY;
      request.price=execution_entry;
   }
   else if(side=="SELL")
   {
      request.action=TRADE_ACTION_DEAL;
      request.type=ORDER_TYPE_SELL;
      request.price=execution_entry;
   }
   else if(side=="BUY_LIMIT")
   {
      request.action=TRADE_ACTION_PENDING;
      request.type=ORDER_TYPE_BUY_LIMIT;
      request.price=entry_price;
      request.type_time=ORDER_TIME_GTC;
      request.type_filling=ORDER_FILLING_RETURN;
   }
   else
   {
      request.action=TRADE_ACTION_PENDING;
      request.type=ORDER_TYPE_SELL_LIMIT;
      request.price=entry_price;
      request.type_time=ORDER_TIME_GTC;
      request.type_filling=ORDER_FILLING_RETURN;
   }

   if(!OrderSend(request,result))
   {
      string msg=StringFormat("OrderSend=false,last_error=%d",GetLastError());
      Print("ALQASEMY EXECUTION FAILED | ",msg);
      Report(command_id,"failed",0,0,msg,0);
      return false;
   }

   bool success=(result.retcode==TRADE_RETCODE_DONE ||
                 result.retcode==TRADE_RETCODE_PLACED ||
                 result.retcode==TRADE_RETCODE_DONE_PARTIAL);
   if(!success)
   {
      string desc=StringFormat("retcode=%d comment=%s",result.retcode,result.comment);
      Print("ALQASEMY TRADE REJECTED | ",desc);
      Report(command_id,"failed",result.order,result.deal,desc,0);
      return false;
   }

   datetime now=TimeCurrent();
   if(canonical=="XAUUSD") last_trade_time_xau=now;
   if(canonical=="EURUSD") last_trade_time_eur=now;

   double fill=(result.price>0 ? result.price : protection_entry);
   Report(command_id,"executed",result.order,result.deal,"",fill);
   Print("ALQASEMY EXECUTED | ",side," | ",symbol," | volume=",DoubleToString(volume,2)," | price=",DoubleToString(fill,digits));
   return true;
}

// ------------------------------------------------------------------
// Command polling
// ------------------------------------------------------------------
void Poll()
{
   string response;
   string endpoint="/api/v1/mt5/commands?limit=10&ea_id="+EAId;
   if(!Http("GET",endpoint,"",response)) return;

   int p=0;
   int processed=0;
   while((p=StringFind(response,"{",p))>=0)
   {
      int e=StringFind(response,"}",p);
      if(e<0) break;
      string object=StringSubstr(response,p,e-p+1);
      p=e+1;

      string id=JStr(object,"id");
      if(id=="") id=JStr(object,"command_id");
      string symbol=Canonical(JStr(object,"symbol"));
      string side=JStr(object,"order_type");
      if(side=="") side=JStr(object,"side");
      StringToUpper(side);

      double volume=JNum(object,"lot_size");
      if(volume<=0) volume=JNum(object,"volume");
      double entry=JNum(object,"entry_price");
      double sl=JNum(object,"stop_loss"); if(sl<=0) sl=JNum(object,"sl");
      double tp=JNum(object,"take_profit"); if(tp<=0) tp=JNum(object,"tp");
      double created_epoch=JNum(object,"created_epoch");

      if(id=="" || symbol=="" || volume<=0) continue;
      if(BrokerSymbol(symbol)=="") { Report(id,"failed",0,0,"UNSUPPORTED_SYMBOL",0); continue; }

      if(created_epoch>0)
      {
         double age=(double)TimeCurrent()-created_epoch;
         if(age<MinCommandAgeSeconds || age>MaxCommandAgeSeconds)
         {
            string msg=(age<MinCommandAgeSeconds ? "COMMAND_TOO_NEW" : "COMMAND_EXPIRED");
            Report(id,(age<MinCommandAgeSeconds ? "ignored" : "expired"),0,0,msg,0);
            continue;
         }
      }

      string ack;
      if(!Http("POST","/api/v1/mt5/commands/"+id+"/ack?ea_id="+EAId,"",ack))
      {
         // If another EA/process already claimed it, do not execute it.
         continue;
      }

      Execute(id,side,symbol,volume,entry,sl,tp);
      processed++;
      if(processed>=10) break;
   }
}

// ------------------------------------------------------------------
// Synchronization
// ------------------------------------------------------------------
int InitialCandleCount(ENUM_TIMEFRAMES timeframe)
{
   if(timeframe==DirectionTimeframe) return MathMax(60,DirectionCandlesInitial);
   if(timeframe==ConfirmationTimeframe) return MathMax(60,ConfirmationCandlesInitial);
   if(timeframe==EntryTimeframe) return MathMax(60,EntryCandlesInitial);
   return 60;
}

string TimeframeName(ENUM_TIMEFRAMES timeframe)
{
   string tf=EnumToString(timeframe);
   StringReplace(tf,"PERIOD_","");
   return tf;
}

datetime ParseIsoTime(string value)
{
   if(StringLen(value)<19) return 0;
   string v=StringSubstr(value,0,19);
   StringReplace(v,"-",".");
   StringReplace(v,"T"," ");
   return StringToTime(v);
}

datetime BackendLastCandleTime(string symbol,ENUM_TIMEFRAMES timeframe)
{
   string response;
   string endpoint="/api/v1/mt5/candles/status?symbol="+Canonical(symbol)+"&timeframe="+TimeframeName(timeframe);
   if(!Http("GET",endpoint,"",response)) return 0;
   string last=JStr(response,"last_open_time");
   if(last=="") return 0;
   return ParseIsoTime(last);
}

string BuildCandleArray(string symbol,ENUM_TIMEFRAMES timeframe,datetime last_backend_time,int max_count)
{
   MqlRates rates[];
   ArraySetAsSeries(rates,true);

   int count_request=0;
   int shift=0;
   if(last_backend_time<=0)
   {
      count_request=InitialCandleCount(timeframe);
      count_request=MathMin(count_request,max_count);
      if(count_request<=0) return "";
      if(CopyRates(symbol,timeframe,1,count_request,rates)<=0) return "";
   }
   else
   {
      shift=iBarShift(symbol,timeframe,last_backend_time,false);
      if(shift<1) return "";
      count_request=MathMin(shift,max_count);
      if(count_request<=0) return "";
      if(CopyRates(symbol,timeframe,shift,count_request,rates)<=0) return "";
   }

   datetime current_open=iTime(symbol,timeframe,0);
   if(current_open<=0) return "";

   int digits=(int)SymbolInfoInteger(symbol,SYMBOL_DIGITS);
   string tf=TimeframeName(timeframe);
   string canonical=Canonical(symbol);
   string array="";

   for(int i=ArraySize(rates)-1;i>=0;i--)
   {
      // Only closed candles are allowed. On recovery, include the last stored
      // candle once for idempotent reconciliation; the database unique key
      // makes this safe and guarantees no duplicates.
      if(rates[i].time>=current_open) continue;
      if(last_backend_time>0 && rates[i].time<last_backend_time) continue;

      string item=StringFormat(
         "{\"symbol\":\"%s\",\"timeframe\":\"%s\",\"open_time\":\"%s\",\"open\":%s,\"high\":%s,\"low\":%s,\"close\":%s,\"volume\":%I64d}",
         EscapeJson(canonical),EscapeJson(tf),IsoTime(rates[i].time),
         DoubleToString(rates[i].open,digits),DoubleToString(rates[i].high,digits),
         DoubleToString(rates[i].low,digits),DoubleToString(rates[i].close,digits),rates[i].tick_volume);
      if(array!="") array+=",";
      array+=item;
   }
   return array;
}

bool SyncTimeframe(string symbol,ENUM_TIMEFRAMES timeframe)
{
   int rounds=0;
   while(rounds<CandleRecoveryRoundsPerSync)
   {
      datetime last_backend_time=BackendLastCandleTime(symbol,timeframe);
      int batch=MathMax(1,CandleRecoveryBatch);
      string candles=BuildCandleArray(symbol,timeframe,last_backend_time,batch);
      if(candles=="") return true;

      string candle_body=StringFormat(
         "{\"candles\":[%s],\"source\":\"MT5_EA\",\"ea_id\":\"%s\"}",
         candles,EscapeJson(EAId));
      string out;
      if(!Http("POST","/api/v1/mt5/candles/sync",candle_body,out)) return false;

      rounds++;
      // If the backend was already current, the returned batch can contain
      // only the latest stored candle. A second status check will then produce
      // no new data and exit. This keeps synchronization idempotent.
   }
   return true;
}

void SyncSymbol(string symbol)
{
   if(!SymbolSelect(symbol,true)) return;

   // Real broker specification -> backend risk engine.
   int digits=(int)SymbolInfoInteger(symbol,SYMBOL_DIGITS);
   double point=SymbolInfoDouble(symbol,SYMBOL_POINT);
   double tick_size=SymbolInfoDouble(symbol,SYMBOL_TRADE_TICK_SIZE);
   double tick_value=SymbolInfoDouble(symbol,SYMBOL_TRADE_TICK_VALUE);
   double vmin=SymbolInfoDouble(symbol,SYMBOL_VOLUME_MIN);
   double vmax=SymbolInfoDouble(symbol,SYMBOL_VOLUME_MAX);
   double vstep=SymbolInfoDouble(symbol,SYMBOL_VOLUME_STEP);
   int stops=(int)SymbolInfoInteger(symbol,SYMBOL_TRADE_STOPS_LEVEL);
   double contract=SymbolInfoDouble(symbol,SYMBOL_TRADE_CONTRACT_SIZE);

   if(point<=0 || tick_size<=0 || tick_value<=0 || vmin<=0 || vmax<=0 || vstep<=0) return;

   string body=StringFormat(
      "{\"symbol\":\"%s\",\"digits\":%d,\"point\":%.12f,\"tick_size\":%.12f,\"tick_value\":%.12f,\"volume_min\":%.8f,\"volume_max\":%.8f,\"volume_step\":%.8f,\"stops_level_points\":%d,\"contract_size\":%.8f}",
      EscapeJson(Canonical(symbol)),digits,point,tick_size,tick_value,vmin,vmax,vstep,stops,contract);
   string out;
   Http("POST","/api/v1/mt5/specs/sync",body,out);

   ENUM_TIMEFRAMES timeframes[3];
   timeframes[0]=DirectionTimeframe;
   timeframes[1]=ConfirmationTimeframe;
   timeframes[2]=EntryTimeframe;
   for(int t=0;t<3;t++)
      SyncTimeframe(symbol,timeframes[t]);
}

void SyncPositions()
{
   long login=(long)AccountInfoInteger(ACCOUNT_LOGIN);
   string positions="";
   for(int i=0;i<PositionsTotal();i++)
   {
      ulong ticket=PositionGetTicket(i);
      if(ticket==0) continue;
      if((long)PositionGetInteger(POSITION_MAGIC)!=Magic) continue;
      string symbol=Canonical(PositionGetString(POSITION_SYMBOL));
      long type=PositionGetInteger(POSITION_TYPE);
      string side=(type==POSITION_TYPE_BUY ? "BUY" : "SELL");
      double volume=PositionGetDouble(POSITION_VOLUME);
      double entry=PositionGetDouble(POSITION_PRICE_OPEN);
      double sl=PositionGetDouble(POSITION_SL);
      double tp=PositionGetDouble(POSITION_TP);
      double profit=PositionGetDouble(POSITION_PROFIT);
      datetime opened=(datetime)PositionGetInteger(POSITION_TIME);
      string item=StringFormat(
         "{\"ticket\":\"%I64d\",\"symbol\":\"%s\",\"side\":\"%s\",\"volume\":%.8f,\"price_open\":%.10f,\"stop_loss\":%.10f,\"take_profit\":%.10f,\"profit\":%.4f}",
         (long)ticket,EscapeJson(symbol),side,volume,entry,sl,tp,profit);
      if(positions!="") positions+=",";
      positions+=item;
   }

   string body=StringFormat("{\"account_number\":%I64d,\"ea_id\":\"%s\",\"positions\":[%s]}",login,EscapeJson(EAId),positions);
   string out;
   Http("POST","/api/v1/mt5/positions/sync",body,out);
}

void SyncPendingOrders()
{
   long login=(long)AccountInfoInteger(ACCOUNT_LOGIN);
   string orders="";
   for(int i=0;i<OrdersTotal();i++)
   {
      ulong ticket=OrderGetTicket(i);
      if(ticket==0) continue;
      if((long)OrderGetInteger(ORDER_MAGIC)!=Magic) continue;
      ENUM_ORDER_TYPE type=(ENUM_ORDER_TYPE)OrderGetInteger(ORDER_TYPE);
      string side="";
      if(type==ORDER_TYPE_BUY_LIMIT) side="BUY_LIMIT";
      else if(type==ORDER_TYPE_SELL_LIMIT) side="SELL_LIMIT";
      else if(type==ORDER_TYPE_BUY_STOP) side="BUY_STOP";
      else if(type==ORDER_TYPE_SELL_STOP) side="SELL_STOP";
      else continue;

      string symbol=Canonical(OrderGetString(ORDER_SYMBOL));
      double volume=OrderGetDouble(ORDER_VOLUME_CURRENT);
      double entry=OrderGetDouble(ORDER_PRICE_OPEN);
      double sl=OrderGetDouble(ORDER_SL);
      double tp=OrderGetDouble(ORDER_TP);
      string item=StringFormat(
         "{\"ticket\":\"%I64d\",\"symbol\":\"%s\",\"side\":\"%s\",\"volume\":%.8f,\"price_open\":%.10f,\"stop_loss\":%.10f,\"take_profit\":%.10f}",
         (long)ticket,EscapeJson(symbol),side,volume,entry,sl,tp);
      if(orders!="") orders+=",";
      orders+=item;
   }
   string body=StringFormat("{\"account_number\":%I64d,\"ea_id\":\"%s\",\"orders\":[%s]}",login,EscapeJson(EAId),orders);
   string out;
   Http("POST","/api/v1/mt5/pending-orders/sync",body,out);
}

void SyncAccount()
{
   long login=(long)AccountInfoInteger(ACCOUNT_LOGIN);
   double balance=AccountInfoDouble(ACCOUNT_BALANCE);
   double equity=AccountInfoDouble(ACCOUNT_EQUITY);
   double margin=AccountInfoDouble(ACCOUNT_MARGIN);
   double free_margin=AccountInfoDouble(ACCOUNT_MARGIN_FREE);
   double profit=equity-balance;
   double margin_level=(margin>0 ? equity/margin*100.0 : 0.0);

   string body=StringFormat(
      "{\"account\":{\"account_number\":%I64d,\"login\":%I64d,\"equity\":%.4f,\"balance\":%.4f,\"margin\":%.4f,\"free_margin\":%.4f,\"profit\":%.4f,\"is_connected\":true,\"margin_level\":%.4f,\"captured_at\":\"%s\",\"ea_id\":\"%s\",\"server\":\"%s\",\"currency\":\"%s\",\"leverage\":%d}}",
      login,login,equity,balance,margin,free_margin,profit,margin_level,IsoTime(TimeCurrent()),
      EscapeJson(EAId),EscapeJson(AccountInfoString(ACCOUNT_SERVER)),EscapeJson(AccountInfoString(ACCOUNT_CURRENCY)),(int)AccountInfoInteger(ACCOUNT_LEVERAGE));
   string out;
   Http("POST","/api/v1/mt5/account/sync",body,out);
}

void SyncHeartbeat()
{
   long login=(long)AccountInfoInteger(ACCOUNT_LOGIN);
   double balance=AccountInfoDouble(ACCOUNT_BALANCE);
   double equity=AccountInfoDouble(ACCOUNT_EQUITY);
   double margin=AccountInfoDouble(ACCOUNT_MARGIN);
   double free_margin=AccountInfoDouble(ACCOUNT_MARGIN_FREE);
   double profit=equity-balance;
   double margin_level=(margin>0 ? equity/margin*100.0 : 0.0);
   string body=StringFormat(
      "{\"account_number\":%I64d,\"balance\":%.4f,\"equity\":%.4f,\"margin\":%.4f,\"free_margin\":%.4f,\"profit\":%.4f,\"is_connected\":true,\"margin_level\":%.4f}",
      login,balance,equity,margin,free_margin,profit,margin_level);
   string out;
   Http("POST","/api/v1/mt5/heartbeat",body,out);
}

void Sync()
{
   SyncAccount();
   SyncPositions();
   SyncPendingOrders();
   SyncHeartbeat();
   SyncSymbol(SymbolEUR);
   SyncSymbol(SymbolXAU);
}

// ------------------------------------------------------------------
// Trade management
// ------------------------------------------------------------------
void ManageOpenTrades()
{
   if(BreakevenPoints<=0 && TrailingStartPoints<=0) return;

   for(int i=PositionsTotal()-1;i>=0;i--)
   {
      ulong ticket=PositionGetTicket(i);
      if(ticket==0) continue;
      if((long)PositionGetInteger(POSITION_MAGIC)!=Magic) continue;

      string sym=PositionGetString(POSITION_SYMBOL);
      double point=SymbolInfoDouble(sym,SYMBOL_POINT);
      int digits=(int)SymbolInfoInteger(sym,SYMBOL_DIGITS);
      long stops=(long)SymbolInfoInteger(sym,SYMBOL_TRADE_STOPS_LEVEL);
      long freeze=(long)SymbolInfoInteger(sym,SYMBOL_TRADE_FREEZE_LEVEL);
      double min_dist=MathMax((double)MathMax(stops,freeze),1.0)*point;
      double current_sl=PositionGetDouble(POSITION_SL);
      double current_tp=PositionGetDouble(POSITION_TP);
      double open_price=PositionGetDouble(POSITION_PRICE_OPEN);
      double current_price=PositionGetDouble(POSITION_PRICE_CURRENT);
      long type=PositionGetInteger(POSITION_TYPE);
      double new_sl=current_sl;

      if(type==POSITION_TYPE_BUY)
      {
         if(BreakevenPoints>0 && current_price-open_price>=BreakevenPoints*point)
            if(current_sl==0 || current_sl<open_price) new_sl=open_price;

         if(TrailingStartPoints>0 && current_price-open_price>=TrailingStartPoints*point)
         {
            double candidate=current_price-TrailingStepPoints*point;
            candidate=MathMin(candidate,current_price-min_dist);
            if(candidate>current_sl && candidate>open_price) new_sl=candidate;
         }
      }
      else
      {
         if(BreakevenPoints>0 && open_price-current_price>=BreakevenPoints*point)
            if(current_sl==0 || current_sl>open_price) new_sl=open_price;

         if(TrailingStartPoints>0 && open_price-current_price>=TrailingStartPoints*point)
         {
            double candidate=current_price+TrailingStepPoints*point;
            candidate=MathMax(candidate,current_price+min_dist);
            if((current_sl==0 || candidate<current_sl) && candidate<open_price) new_sl=candidate;
         }
      }

      new_sl=NormalizeDouble(new_sl,digits);
      if(new_sl!=0 && MathAbs(new_sl-current_sl)>=point)
      {
         ResetLastError();
         if(!trade.PositionModify(ticket,new_sl,current_tp))
            Print("ALQASEMY management modify failed | ticket=",ticket," | err=",GetLastError());
      }
   }
}

// ------------------------------------------------------------------
// Lifecycle
// ------------------------------------------------------------------
int OnInit()
{
   if(StringLen(Url())<10) return INIT_FAILED;
   if(StringLen(EAToken)<16 || EAToken=="CHANGE_ME")
   {
      Print("ALQASEMY: set a real EAToken before attaching the EA.");
      return INIT_FAILED;
   }

   trade.SetExpertMagicNumber(Magic);
   EventSetTimer(1);
   Print("ALQASEMY TRADER EA v11.0 MTF started | EA=",EAId," | Magic=",Magic);

   // Backend must be reachable before trading is considered operational.
   string response;
   if(!Http("GET","/api/v1/mt5/commands?limit=1&ea_id="+EAId,"",response))
   {
      Print("ALQASEMY: backend authentication/connectivity test failed.");
      return INIT_FAILED;
   }
   Sync();
   return INIT_SUCCEEDED;
}

void OnDeinit(const int reason)
{
   EventKillTimer();
   Print("ALQASEMY TRADER EA v11.0 stopped. reason=",reason);
}

void OnTimer()
{
   datetime now=TimeCurrent();
   if(now-last_poll>=PollSeconds) { last_poll=now; Poll(); }
   if(now-last_sync>=SyncSeconds) { last_sync=now; Sync(); }
}

void OnTick()
{
   ManageOpenTrades();
}
//+------------------------------------------------------------------+
