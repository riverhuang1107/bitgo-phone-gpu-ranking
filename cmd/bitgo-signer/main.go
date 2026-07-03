package main

import (
	"encoding/json"
	"fmt"
	"os"

	"bitgo-phone-cell-filter/internal/signing"
)

func main() {
	var input signing.Input
	if err := json.NewDecoder(os.Stdin).Decode(&input); err != nil {
		fmt.Fprintf(os.Stderr, "decode input: %v\n", err)
		os.Exit(2)
	}
	headers, err := signing.CreateHeaders(input)
	if err != nil {
		fmt.Fprintf(os.Stderr, "%v\n", err)
		os.Exit(1)
	}
	if err := json.NewEncoder(os.Stdout).Encode(headers); err != nil {
		fmt.Fprintf(os.Stderr, "encode headers: %v\n", err)
		os.Exit(1)
	}
}
