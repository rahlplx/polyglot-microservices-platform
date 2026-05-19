/**
 * Money Value Object
 *
 * Represents a monetary amount with currency, following the common.v1.Money
 * protobuf definition. Precision-safe using integer units + nanos pattern.
 *
 * Domain core has ZERO external dependencies.
 */
export class Money {
  public readonly currencyCode: string;
  public readonly units: number;
  public readonly nanos: number;

  private constructor(currencyCode: string, units: number, nanos: number) {
    this.currencyCode = currencyCode;
    this.units = units;
    this.nanos = nanos;
  }

  /**
   * Create a Money value object with validation.
   * Nanos must be same sign as units and in range [0, 1_000_000_000).
   */
  public static create(currencyCode: string, units: number, nanos: number): Money {
    if (!currencyCode || currencyCode.length !== 3) {
      throw new MoneyValidationError(
        `Invalid currency code: "${currencyCode}". Must be a 3-letter ISO 4217 code.`
      );
    }

    if (!Number.isInteger(units)) {
      throw new MoneyValidationError(
        `Units must be an integer, got: ${units}`
      );
    }

    if (!Number.isInteger(nanos)) {
      throw new MoneyValidationError(
        `Nanos must be an integer, got: ${nanos}`
      );
    }

    if (nanos <= -1_000_000_000 || nanos >= 1_000_000_000) {
      throw new MoneyValidationError(
        `Nanos must be in range [-999999999, 999999999], got: ${nanos}`
      );
    }

    // Sign consistency: nanos must be same sign as units (or zero)
    if (units > 0 && nanos < 0) {
      throw new MoneyValidationError(
        'Nanos must have the same sign as units (both positive or both negative).'
      );
    }
    if (units < 0 && nanos > 0) {
      throw new MoneyValidationError(
        'Nanos must have the same sign as units (both positive or both negative).'
      );
    }

    return new Money(currencyCode, units, nanos);
  }

  /**
   * Create Money from a decimal string, e.g. "29.99" with currency "USD".
   */
  public static fromDecimal(currencyCode: string, amount: string): Money {
    const parts = amount.split('.');
    const wholePart = parseInt(parts[0], 10);
    const decimalStr = parts[1] ?? '0';
    const paddedDecimal = decimalStr.padEnd(9, '0').slice(0, 9);
    let nanos = parseInt(paddedDecimal, 10);

    if (wholePart < 0) {
      nanos = -nanos;
    }

    return Money.create(currencyCode, wholePart, nanos);
  }

  /**
   * Create a zero-value Money in the given currency.
   */
  public static zero(currencyCode: string): Money {
    return new Money(currencyCode, 0, 0);
  }

  /**
   * Convert to a decimal string representation.
   */
  public toDecimal(): string {
    const sign = this.units < 0 || this.nanos < 0 ? '-' : '';
    const absUnits = Math.abs(this.units);
    const absNanos = Math.abs(this.nanos);
    const nanosStr = absNanos.toString().padStart(9, '0').replace(/0+$/, '');
    if (nanosStr.length === 0) {
      return `${sign}${absUnits}`;
    }
    return `${sign}${absUnits}.${nanosStr}`;
  }

  /**
   * Add two Money values of the same currency.
   */
  public add(other: Money): Money {
    this.assertSameCurrency(other);
    const totalNanos = this.nanos + other.nanos;
    const carry = Math.trunc(totalNanos / 1_000_000_000);
    const remainderNanos = totalNanos % 1_000_000_000;
    const resultUnits = this.units + other.units + carry;
    return new Money(this.currencyCode, resultUnits, remainderNanos);
  }

  /**
   * Subtract another Money value of the same currency.
   */
  public subtract(other: Money): Money {
    this.assertSameCurrency(other);
    const negated = new Money(other.currencyCode, -other.units, -other.nanos);
    return this.add(negated);
  }

  /**
   * Check if this Money is greater than another.
   */
  public greaterThan(other: Money): boolean {
    this.assertSameCurrency(other);
    if (this.units !== other.units) {
      return this.units > other.units;
    }
    return this.nanos > other.nanos;
  }

  /**
   * Check if this Money is less than another.
   */
  public lessThan(other: Money): boolean {
    this.assertSameCurrency(other);
    if (this.units !== other.units) {
      return this.units < other.units;
    }
    return this.nanos < other.nanos;
  }

  /**
   * Check equality with another Money value.
   */
  public equals(other: Money): boolean {
    return (
      this.currencyCode === other.currencyCode &&
      this.units === other.units &&
      this.nanos === other.nanos
    );
  }

  /**
   * Check if the amount is zero.
   */
  public isZero(): boolean {
    return this.units === 0 && this.nanos === 0;
  }

  /**
   * Check if the amount is negative.
   */
  public isNegative(): boolean {
    return this.units < 0 || (this.units === 0 && this.nanos < 0);
  }

  private assertSameCurrency(other: Money): void {
    if (this.currencyCode !== other.currencyCode) {
      throw new MoneyValidationError(
        `Currency mismatch: cannot operate on ${this.currencyCode} and ${other.currencyCode}`
      );
    }
  }
}

/**
 * Validation error for Money value object.
 */
export class MoneyValidationError extends Error {
  public readonly code = 'MONEY_VALIDATION_ERROR';

  constructor(message: string) {
    super(message);
    this.name = 'MoneyValidationError';
  }
}
