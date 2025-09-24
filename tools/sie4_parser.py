# sie4_parser.py
from __future__ import annotations
from dataclasses import dataclass, field
from typing import Dict, List, Optional, Tuple, Iterable
from datetime import date, datetime
import re

try:
    import pandas as pd  # Optional, but handy
except ImportError:
    pd = None


# ---------------------------
# Domain model
# ---------------------------

@dataclass
class Account:
    number: str
    name: str = ""
    parent: Optional["Account"] = None
    children: List["Account"] = field(default_factory=list)
    sru: Optional[str] = None
    opening_balance: Optional[float] = None  # #IB
    closing_balance: Optional[float] = None  # #UB

    def lineage(self) -> List["Account"]:
        node, chain = self, []
        while node is not None:
            chain.append(node)
            node = node.parent
        return list(reversed(chain))

@dataclass
class Transaction:
    account: str
    amount: float
    dim: Optional[Tuple[str, ...]] = None  # placeholder for dimensions like object/enhet
    text: Optional[str] = None

@dataclass
class Voucher:
    series: str
    number: str
    date: date
    text: str = ""
    reg_date: Optional[date] = None
    transactions: List[Transaction] = field(default_factory=list)

@dataclass
class RAR:  # Räkenskapsår
    idx: int
    start: date
    end: date

@dataclass
class Company:
    orgnr: Optional[str] = None
    name: Optional[str] = None
    program: Optional[str] = None
    sietyp: Optional[str] = None
    format: Optional[str] = None
    generated: Optional[date] = None
    rars: List[RAR] = field(default_factory=list)
    accounts: Dict[str, Account] = field(default_factory=dict)
    vouchers: List[Voucher] = field(default_factory=list)

    # --- Pandas helpers ---
    def to_pandas_accounts(self):
        if pd is None:
            raise ImportError("pandas is not installed")
        rows = []
        for acc in self.accounts.values():
            parent = acc.parent.number if acc.parent else None
            rows.append({
                "account": acc.number,
                "name": acc.name,
                "parent": parent,
                "sru": acc.sru,
                "opening_balance": acc.opening_balance,
                "closing_balance": acc.closing_balance,
            })
        return pd.DataFrame(rows).sort_values("account")

    def to_pandas_vouchers(self):
        if pd is None:
            raise ImportError("pandas is not installed")
        rows = []
        for v in self.vouchers:
            rows.append({
                "series": v.series,
                "number": v.number,
                "date": pd.to_datetime(v.date),
                "text": v.text,
                "reg_date": pd.to_datetime(v.reg_date) if v.reg_date else None,
                "n_transactions": len(v.transactions),
            })
        return pd.DataFrame(rows).sort_values(["date", "series", "number"])

    def to_pandas_transactions(self):
        if pd is None:
            raise ImportError("pandas is not installed")
        rows = []
        for v in self.vouchers:
            for i, t in enumerate(v.transactions, start=1):
                rows.append({
                    "series": v.series,
                    "number": v.number,
                    "voucher_date": pd.to_datetime(v.date),
                    "voucher_text": v.text,
                    "tx_index": i,
                    "account": t.account,
                    "amount": t.amount,
                    "dim": t.dim,
                    "text": t.text,
                })
        df = pd.DataFrame(rows)
        if not df.empty:
            df["month"] = df["voucher_date"].dt.to_period("M").astype(str)
        return df

    def to_pandas_monthly_by_account(self):
        """
        Sum of amounts per month and account (debit positive, credit negative per SIE sign).
        """
        if pd is None:
            raise ImportError("pandas is not installed")
        tx = self.to_pandas_transactions()
        if tx.empty:
            return tx
        pivot = (tx
                 .groupby(["account", "month"], as_index=False)["amount"]
                 .sum()
                 .pivot(index="account", columns="month", values="amount")
                 .fillna(0.0)
                 .sort_index())
        # Optionally join account names:
        acc = self.to_pandas_accounts().set_index("account")[["name"]]
        return acc.join(pivot, how="left").fillna(0.0)


# ---------------------------
# SIE4 Parser
# ---------------------------

class SIE4Parser:
    """
    Minimal but robust SIE4 parser.

    Supports:
      - #FLAGGA, #PROGRAM, #FORMAT, #GEN, #SIETYP
      - #ORGNR, #FNAMN
      - #RAR
      - #KONTO, #SRU
      - #IB, #UB
      - #VER { #TRANS ... }
    """

    def __init__(self, infer_account_hierarchy: bool = True):
        self.infer_account_hierarchy = infer_account_hierarchy

    def parse(self, path: str, encoding_candidates: Iterable[str] = ("cp1252", "latin1", "utf-8")) -> Company:
        text = self._read_text_with_guess(path, encoding_candidates)
        lines = self._normalize_lines(text)
        company = Company()
        ctx_in_ver_block = False
        current_voucher: Optional[Voucher] = None

        for raw in lines:
            line = raw.strip()
            if not line or line.startswith(";;"):  # comment line
                continue

            # Handle block delimiters
            if line == "{":
                ctx_in_ver_block = True
                continue
            if line == "}":
                ctx_in_ver_block = False
                if current_voucher:
                    company.vouchers.append(current_voucher)
                    current_voucher = None
                continue

            if not line.startswith("#"):
                # Some files may have non-command lines; skip safely
                continue

            cmd, args = self._split_command(line)

            if cmd == "#FLAGGA":
                pass  # ignore
            elif cmd == "#PROGRAM":
                # #PROGRAM "Name with spaces" 1.0 20240305
                program = " ".join(a for a in args if a)
                company.program = program.strip()
            elif cmd == "#FORMAT":
                company.format = args[0] if args else None
            elif cmd == "#GEN":
                company.generated = self._parse_date(args[0]) if args else None
            elif cmd == "#SIETYP":
                company.sietyp = args[0] if args else None
            elif cmd == "#ORGNR":
                company.orgnr = args[0] if args else None
            elif cmd == "#FNAMN":
                company.name = self._strip_quotes(args[0]) if args else None
            elif cmd == "#RAR":
                # #RAR idx yyyymmdd yyyymmdd
                rar = RAR(idx=int(args[0]),
                          start=self._parse_date(args[1]),
                          end=self._parse_date(args[2]))
                company.rars.append(rar)
            elif cmd == "#KONTO":
                # #KONTO 3001 "Försäljning"
                acc_no = args[0]
                acc_name = self._strip_quotes(args[1]) if len(args) > 1 else ""
                acc = company.accounts.get(acc_no) or Account(number=acc_no)
                acc.name = acc_name or acc.name
                company.accounts[acc_no] = acc
            elif cmd == "#SRU":
                # #SRU 3001 7200
                if len(args) >= 2:
                    acc_no, sru = args[0], args[1]
                    acc = company.accounts.get(acc_no) or Account(number=acc_no)
                    acc.sru = sru
                    company.accounts[acc_no] = acc
            elif cmd == "#IB":
                # #IB 1930 10000.00
                acc_no, amount = args[0], float(args[1].replace(",", "."))
                acc = company.accounts.get(acc_no) or Account(number=acc_no)
                acc.opening_balance = amount
                company.accounts[acc_no] = acc
            elif cmd == "#UB":
                # #UB 1930 20000.00
                acc_no, amount = args[0], float(args[1].replace(",", "."))
                acc = company.accounts.get(acc_no) or Account(number=acc_no)
                acc.closing_balance = amount
                company.accounts[acc_no] = acc
            elif cmd == "#VER":
                # #VER A 1 20240110 "Text" 20240110
                series = args[0]
                number = args[1]
                vdate = self._parse_date(args[2])
                text = self._strip_quotes(args[3]) if len(args) > 3 else ""
                reg_date = self._parse_date(args[4]) if len(args) > 4 else None
                current_voucher = Voucher(series=series, number=number, date=vdate, text=text, reg_date=reg_date)
            elif cmd == "#TRANS":
                # #TRANS 1930 -1000.00 "text" [dim...]
                if current_voucher is None:
                    # Malformed file; skip gracefully
                    continue
                acc_no = args[0]
                amount = float(args[1].replace(",", "."))
                # remaining args could be "text" and/or dimensions; we only capture text if quoted
                tx_text = None
                if len(args) >= 3 and self._is_quoted(args[2]):
                    tx_text = self._strip_quotes(args[2])
                    dims = tuple(args[3:]) if len(args) > 3 else None
                else:
                    dims = tuple(args[2:]) if len(args) > 2 else None
                current_voucher.transactions.append(Transaction(account=acc_no, amount=amount, dim=dims, text=tx_text))
            else:
                # Ignore other commands for now (#RES, #KUND, #LEVERANTOR, etc.)
                pass

        # Build inferred account tree if requested
        if self.infer_account_hierarchy and company.accounts:
            self._build_account_hierarchy(company.accounts)

        return company

    # ---------------------------
    # Helpers
    # ---------------------------

    @staticmethod
    def _read_text_with_guess(path: str, encodings: Iterable[str]) -> str:
        last_exc = None
        for enc in encodings:
            try:
                with open(path, "r", encoding=enc, errors="strict") as f:
                    return f.read()
            except Exception as e:
                last_exc = e
                continue
        # fallback with replacement to at least get something
        with open(path, "r", encoding="latin1", errors="replace") as f:
            return f.read()

    @staticmethod
    def _normalize_lines(text: str) -> List[str]:
        # Some SIE files have CRLF or exotic endings; normalize
        return text.replace("\r\n", "\n").replace("\r", "\n").split("\n")

    @staticmethod
    def _parse_date(s: str) -> date:
        # yyyymmdd
        s = re.sub(r'[^0-9]', '', s)
        return datetime.strptime(s, "%Y%m%d").date()

    @staticmethod
    def _strip_quotes(s: str) -> str:
        if len(s) >= 2 and ((s[0] == s[-1] == '"') or (s[0] == s[-1] == "'")):
            return s[1:-1]
        return s

    @staticmethod
    def _is_quoted(s: str) -> bool:
        return len(s) >= 2 and s[0] in ('"', "'") and s[-1] == s[0]

    @staticmethod
    def _split_command(line: str) -> Tuple[str, List[str]]:
        """
        Split a SIE command line into (command, args) with quote-awareness.

        Example:
          #VER A 1 20240110 "Kundfaktura 1001" 20240110
          -> ("#VER", ["A","1","20240110","\"Kundfaktura 1001\"","20240110"])
        """
        # Find the command token
        m = re.match(r"^(#[A-Z0-9]+)\s*(.*)$", line, re.IGNORECASE)
        if not m:
            return line, []
        cmd, rest = m.group(1), m.group(2)

        args: List[str] = []
        i, n = 0, len(rest)
        while i < n:
            # skip spaces
            while i < n and rest[i].isspace():
                i += 1
            if i >= n:
                break
            if rest[i] in ("'", '"'):
                q = rest[i]
                i += 1
                start = i
                # read until matching quote
                buf = []
                while i < n:
                    ch = rest[i]
                    if ch == q:
                        break
                    buf.append(ch)
                    i += 1
                args.append(q + "".join(buf) + q)
                i += 1  # skip ending quote
            else:
                # read until space
                start = i
                while i < n and not rest[i].isspace():
                    i += 1
                args.append(rest[start:i])
        return cmd.upper(), args

    @staticmethod
    def _build_account_hierarchy(accounts: Dict[str, Account]) -> None:
        """
        Build parent-child relationships by numeric prefix:
          - Parent levels: 1-digit, 2-digit, 3-digit
          - Leaf level: 4-digit (BAS standard), but supports longer
        """
        # Ensure all intermediate prefixes exist as synthetic nodes if needed
        def ensure_account(num: str) -> Account:
            if num not in accounts:
                accounts[num] = Account(number=num, name="")
            return accounts[num]

        # Create parents for each account by prefixes
        for num in list(accounts.keys()):
            # Only consider numeric accounts for hierarchy
            if not num.isdigit():
                continue
            prefixes = [num[:1], num[:2], num[:3]]
            child = ensure_account(num)
            for p in prefixes:
                if p == num:
                    continue
                parent = ensure_account(p)
                # Link if not already linked and doesn't create cycle
                if child.parent is None and parent is not child:
                    # pick the deepest existing parent (3 -> 2 -> 1)
                    # We’ll assign after loop to the deepest valid
                    pass

        # Assign actual parents preferring deepest prefix that exists
        for num, acc in list(accounts.items()):
            if not num.isdigit() or len(num) == 1:
                continue
            candidates = [num[:i] for i in (len(num) - 1, len(num) - 2, len(num) - 3, 1, 2, 3) if i > 0]
            # prefer 3-digit, then 2, then 1
            pref = []
            if len(num) >= 4:
                pref = [num[:3], num[:2], num[:1]]
            elif len(num) == 3:
                pref = [num[:2], num[:1]]
            elif len(num) == 2:
                pref = [num[:1]]
            for p in pref:
                if p in accounts and p != num:
                    parent = accounts[p]
                    if acc.parent is None:
                        acc.parent = parent
                        if acc not in parent.children:
                            parent.children.append(acc)
                        break
        # Ensure top-level nodes (1-digit) have no parent:
        for num, acc in accounts.items():
            if num.isdigit() and len(num) == 1:
                acc.parent = None  # root

# ---------------------------
# Example usage (remove if importing as a library)
# ---------------------------
if __name__ == "__main__":
    import sys
    if len(sys.argv) < 2:
        print("Usage: python sie4_parser.py <path_to_sie4_file>")
        sys.exit(1)
    parser = SIE4Parser()
    company = parser.parse(sys.argv[1])
    print(f"Company: {company.name} ({company.orgnr}) – SIETYP {company.sietyp}")
    print(f"Accounts: {len(company.accounts)} | Vouchers: {len(company.vouchers)}")
    if pd:
        df_tx = company.to_pandas_transactions()
        print(df_tx.head())