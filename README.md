# Phone GPU Rank CLI

CLI tool for generating a May 2026 smartphone GPU performance ranking report through the bitgo wallet-signed external reasoning API.

## Requirements

- Python 3.11+
- Go 1.22+
- A funded bitgo wallet configuration provided through environment variables

## Environment

Do not store real private keys in this repository.

Required:

```powershell
$env:BITGO_WALLET_CHAIN = "btc" # btc, ltc, or eth
$env:BITGO_WALLET_ADDRESS = "YOUR_WALLET_ADDRESS"
$env:BITGO_MONEY = "YOUR_MONEY"
$env:BITGO_MONEY_ID = "YOUR_MONEY_ID"
$env:BITGO_WALLET_PRIVATE_KEY = "YOUR_WIF_OR_ETH_HEX_PRIVATE_KEY"
$env:BITGO_MODEL = "claude-4.6-opus"
```

Optional:

```powershell
$env:BITGO_ENDPOINT = "https://api-token-enigmhaven.expvent.com.cn:1111/v1/messages"
$env:BITGO_TOOLS_JSON = '[{"type":"web_search"}]'
$env:BITGO_MAX_TOKENS = "4096"
```

## Usage

Generate reports:

```powershell
python -m phone_gpu_rank report --format both
```

Generate mail assets and the `agently-cli` send command:

```powershell
python -m phone_gpu_rank mail --to user@example.com --subject "2026年5月手机GPU性能排行"
```

The mail command does not auto-confirm sending. Follow the two-step confirmation flow printed by `agently-cli`.

## Outputs

- `output/phone-gpu-ranking-2026-05.md`
- `output/phone-gpu-ranking-2026-05.html`
- `output/phone-gpu-ranking-2026-05.eml`

