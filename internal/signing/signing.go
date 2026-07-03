package signing

import (
	"crypto/ecdsa"
	"crypto/elliptic"
	"crypto/rand"
	"crypto/sha256"
	"crypto/x509"
	"encoding/base64"
	"encoding/hex"
	"encoding/json"
	"errors"
	"fmt"
	"math/big"
	"strings"

	"github.com/btcsuite/btcd/btcec/v2"
	btcecdsa "github.com/btcsuite/btcd/btcec/v2/ecdsa"
	"github.com/btcsuite/btcd/btcec/v2/schnorr"
	"github.com/btcsuite/btcd/btcutil/base58"
	ethcrypto "github.com/ethereum/go-ethereum/crypto"
)

type Input struct {
	WalletChain      string `json:"wallet_chain"`
	WalletAddress    string `json:"wallet_address"`
	Money            string `json:"money"`
	MoneyID          string `json:"money_id"`
	WalletPrivateKey string `json:"wallet_private_key"`
}

type walletParams struct {
	WalletAddress string `json:"wallet_address"`
	Money         string `json:"money"`
	MoneyID       string `json:"money_id"`
	Signature     string `json:"signature"`
}

func CreateHeaders(input Input) (map[string]string, error) {
	if err := validate(input); err != nil {
		return nil, err
	}
	walletSig, err := signWalletMessage(input)
	if err != nil {
		return nil, err
	}
	paramsJSON, err := json.Marshal(walletParams{
		WalletAddress: input.WalletAddress,
		Money:         input.Money,
		MoneyID:       input.MoneyID,
		Signature:     base64.StdEncoding.EncodeToString(walletSig),
	})
	if err != nil {
		return nil, err
	}
	xParams := base64.StdEncoding.EncodeToString(paramsJSON)
	nonceBytes := make([]byte, 16)
	if _, err := rand.Read(nonceBytes); err != nil {
		return nil, fmt.Errorf("generate nonce: %w", err)
	}
	xNonce := hex.EncodeToString(nonceBytes)
	priv, err := ecdsa.GenerateKey(elliptic.P256(), rand.Reader)
	if err != nil {
		return nil, fmt.Errorf("generate interface key: %w", err)
	}
	digest := sha256.Sum256([]byte(xParams + xNonce))
	derSig, err := ecdsa.SignASN1(rand.Reader, priv, digest[:])
	if err != nil {
		return nil, fmt.Errorf("sign interface request: %w", err)
	}
	pubDER, err := x509.MarshalPKIXPublicKey(&priv.PublicKey)
	if err != nil {
		return nil, fmt.Errorf("marshal interface public key: %w", err)
	}
	return map[string]string{
		"X-Params":    xParams,
		"X-Nonce":     xNonce,
		"X-Signature": hex.EncodeToString(derSig),
		"X-Public-Key": hex.EncodeToString(pubDER),
	}, nil
}

func validate(input Input) error {
	if input.WalletChain == "" || input.WalletAddress == "" || input.Money == "" || input.MoneyID == "" || input.WalletPrivateKey == "" {
		return errors.New("wallet_chain, wallet_address, money, money_id, and wallet_private_key are required")
	}
	return nil
}

func signWalletMessage(input Input) ([]byte, error) {
	msg := []byte(input.WalletAddress + input.Money + input.MoneyID)
	digest := sha256.Sum256(msg)
	switch strings.ToLower(input.WalletChain) {
	case "btc":
		return signBitcoinLike(input.WalletPrivateKey, input.WalletAddress, digest[:], true)
	case "ltc":
		return signBitcoinLike(input.WalletPrivateKey, input.WalletAddress, digest[:], false)
	case "eth":
		key := strings.TrimPrefix(input.WalletPrivateKey, "0x")
		priv, err := ethcrypto.HexToECDSA(key)
		if err != nil {
			return nil, fmt.Errorf("decode eth private key: %w", err)
		}
		return ethcrypto.Sign(digest[:], priv)
	default:
		return nil, fmt.Errorf("unsupported wallet_chain %q", input.WalletChain)
	}
}

func signBitcoinLike(wif string, address string, digest []byte, isBTC bool) ([]byte, error) {
	priv, err := decodeWIFPrivateKey(wif)
	if err != nil {
		return nil, err
	}
	if strings.HasPrefix(strings.ToLower(address), "bc1p") && isBTC {
		tweaked := tweakTaprootPrivKey(priv)
		sig, err := schnorr.Sign(tweaked, digest)
		if err != nil {
			return nil, fmt.Errorf("sign btc taproot wallet message: %w", err)
		}
		return sig.Serialize(), nil
	}
	if strings.HasPrefix(strings.ToLower(address), "ltc1p") && !isBTC {
		sig, err := schnorr.Sign(priv, digest)
		if err != nil {
			return nil, fmt.Errorf("sign ltc taproot wallet message: %w", err)
		}
		return sig.Serialize(), nil
	}
	return btcecdsa.SignCompact(priv, digest, true), nil
}

func decodeWIFPrivateKey(wif string) (*btcec.PrivateKey, error) {
	decoded, _, err := base58.CheckDecode(wif)
	if err != nil {
		return nil, fmt.Errorf("decode WIF private key: %w", err)
	}
	if len(decoded) == 33 && decoded[32] == 0x01 {
		decoded = decoded[:32]
	}
	if len(decoded) != 32 {
		return nil, fmt.Errorf("decode WIF private key: expected 32-byte key, got %d bytes", len(decoded))
	}
	priv, _ := btcec.PrivKeyFromBytes(decoded)
	return priv, nil
}

func tweakTaprootPrivKey(priv *btcec.PrivateKey) *btcec.PrivateKey {
	pubkey := schnorr.SerializePubKey(priv.PubKey())
	tweak := taggedHash("TapTweak", pubkey)
	curveN := btcec.S256().Params().N
	keyInt := new(big.Int).SetBytes(priv.Serialize())
	tweakInt := new(big.Int).SetBytes(tweak)
	keyInt.Add(keyInt, tweakInt)
	keyInt.Mod(keyInt, curveN)
	tweakedBytes := keyInt.FillBytes(make([]byte, 32))
	tweaked, _ := btcec.PrivKeyFromBytes(tweakedBytes)
	return tweaked
}

func taggedHash(tag string, payload []byte) []byte {
	tagHash := sha256.Sum256([]byte(tag))
	h := sha256.New()
	h.Write(tagHash[:])
	h.Write(tagHash[:])
	h.Write(payload)
	return h.Sum(nil)
}
