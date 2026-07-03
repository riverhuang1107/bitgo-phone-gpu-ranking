package signing

import (
	"encoding/base64"
	"encoding/json"
	"testing"
)

func TestCreateHeadersETH(t *testing.T) {
	headers, err := CreateHeaders(Input{
		WalletChain:      "eth",
		WalletAddress:    "0x0000000000000000000000000000000000000001",
		Money:            "6",
		MoneyID:          "20260703001",
		WalletPrivateKey: "0000000000000000000000000000000000000000000000000000000000000001",
	})
	if err != nil {
		t.Fatalf("CreateHeaders returned error: %v", err)
	}
	for _, key := range []string{"X-Params", "X-Nonce", "X-Signature", "X-Public-Key"} {
		if headers[key] == "" {
			t.Fatalf("missing %s", key)
		}
	}
	raw, err := base64.StdEncoding.DecodeString(headers["X-Params"])
	if err != nil {
		t.Fatalf("decode X-Params: %v", err)
	}
	var params walletParams
	if err := json.Unmarshal(raw, &params); err != nil {
		t.Fatalf("unmarshal params: %v", err)
	}
	if params.WalletAddress != "0x0000000000000000000000000000000000000001" {
		t.Fatalf("unexpected wallet address: %s", params.WalletAddress)
	}
	if params.Signature == "" {
		t.Fatal("missing wallet signature")
	}
}

func TestCreateHeadersRequiresFields(t *testing.T) {
	_, err := CreateHeaders(Input{})
	if err == nil {
		t.Fatal("expected validation error")
	}
}
