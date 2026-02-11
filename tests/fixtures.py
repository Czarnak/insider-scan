"""Shared test fixtures: sample HTML for scrapers."""

from __future__ import annotations

# -----------------------------------------------------------------------
# secform4.com sample HTML
# -----------------------------------------------------------------------

SECFORM4_HTML = """
<html>
<body>
<h1>AAPL Insider Trading</h1>
<table>
<tr>
  <th>Insider Name</th>
  <th>Title</th>
  <th>Transaction Type</th>
  <th>Trade Date</th>
  <th>Filing Date</th>
  <th>Shares</th>
  <th>Price</th>
  <th>Value</th>
  <th>Shares Owned After</th>
</tr>
<tr>
  <td>Cook Timothy D</td>
  <td>CEO</td>
  <td>Sale</td>
  <td>2025-11-15</td>
  <td>2025-11-17</td>
  <td>100,000</td>
  <td>$185.50</td>
  <td>$18,550,000</td>
  <td>3,280,000</td>
</tr>
<tr>
  <td>Williams Jeffrey E</td>
  <td>COO</td>
  <td>Sale</td>
  <td>2025-11-10</td>
  <td>2025-11-12</td>
  <td>50,000</td>
  <td>$183.20</td>
  <td>$9,160,000</td>
  <td>1,500,000</td>
</tr>
<tr>
  <td>Maestri Luca</td>
  <td>CFO</td>
  <td>Purchase</td>
  <td>2025-10-01</td>
  <td>2025-10-03</td>
  <td>25,000</td>
  <td>$172.00</td>
  <td>$4,300,000</td>
  <td>800,000</td>
</tr>
<tr>
  <td>Pelosi Nancy</td>
  <td>Director</td>
  <td>Purchase</td>
  <td>2025-09-20</td>
  <td>2025-09-22</td>
  <td>10,000</td>
  <td>$170.00</td>
  <td>$1,700,000</td>
  <td>50,000</td>
</tr>
</table>
</body>
</html>
"""

# -----------------------------------------------------------------------
# openinsider.com sample HTML
# -----------------------------------------------------------------------

OPENINSIDER_HTML = """
<html>
<body>
<table class="tinytable">
<tr>
  <th>Filing Date</th>
  <th>Trade Date</th>
  <th>Ticker</th>
  <th>Company Name</th>
  <th>Insider Name</th>
  <th>Title</th>
  <th>Trade Type</th>
  <th>Qty</th>
  <th>Price</th>
  <th>Value</th>
  <th>Shares Owned After</th>
</tr>
<tr>
  <td>2025-11-17</td>
  <td>2025-11-15</td>
  <td>AAPL</td>
  <td>Apple Inc</td>
  <td>Cook Timothy D</td>
  <td>CEO</td>
  <td>S - Sale</td>
  <td>100,000</td>
  <td>$185.50</td>
  <td>$18,550,000</td>
  <td>3,280,000</td>
</tr>
<tr>
  <td>2025-11-14</td>
  <td>2025-11-12</td>
  <td>MSFT</td>
  <td>Microsoft Corp</td>
  <td>Nadella Satya</td>
  <td>CEO</td>
  <td>S - Sale</td>
  <td>200,000</td>
  <td>$420.00</td>
  <td>$84,000,000</td>
  <td>5,000,000</td>
</tr>
<tr>
  <td>2025-11-10</td>
  <td>2025-11-08</td>
  <td>TSLA</td>
  <td>Tesla Inc</td>
  <td>Tuberville Tommy</td>
  <td>Director</td>
  <td>P - Purchase</td>
  <td>5,000</td>
  <td>$310.00</td>
  <td>$1,550,000</td>
  <td>15,000</td>
</tr>
</table>
</body>
</html>
"""

# -----------------------------------------------------------------------
# EDGAR CIK resolution HTML
# -----------------------------------------------------------------------

EDGAR_CIK_HTML = """
<html>
<body>
<div class="companyInfo">
  <span class="companyName">APPLE INC
    <a href="/cgi-bin/browse-edgar?action=getcompany&amp;CIK=0000320193&amp;type=4">
      CIK=0000320193
    </a>
  </span>
</div>
</body>
</html>
"""

EDGAR_CIK_NOT_FOUND_HTML = """
<html>
<body>
<div>No matching companies found.</div>
</body>
</html>
"""
