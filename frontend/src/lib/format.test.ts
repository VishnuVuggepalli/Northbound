import { describe, expect, it } from 'vitest';
import { isPlausibleArea, isPlausibleCidr, isPlausibleIp } from './format';

describe('isPlausibleIp', () => {
  it('accepts a valid dotted-quad', () => {
    expect(isPlausibleIp('8.8.8.8')).toBe(true);
    expect(isPlausibleIp('10.0.0.1')).toBe(true);
    expect(isPlausibleIp('0.0.0.0')).toBe(true);
  });

  it('rejects leading-zero octets (matches Python backend)', () => {
    expect(isPlausibleIp('01.02.03.04')).toBe(false);
    expect(isPlausibleIp('10.0.0.01')).toBe(false);
  });

  it('rejects out-of-range and garbage', () => {
    expect(isPlausibleIp('999.1.1.1')).toBe(false);
    expect(isPlausibleIp('notanip')).toBe(false);
    expect(isPlausibleIp('')).toBe(false);
    expect(isPlausibleIp('10.0.0.1/24')).toBe(false);
  });
});

describe('isPlausibleCidr', () => {
  it('accepts v4 and v6 with a prefix', () => {
    expect(isPlausibleCidr('10.0.0.1/24')).toBe(true);
    expect(isPlausibleCidr('2001:db8::1/64')).toBe(true);
  });

  it('rejects a bare address with no prefix', () => {
    expect(isPlausibleCidr('10.0.0.1')).toBe(false);
  });

  it('rejects garbage', () => {
    expect(isPlausibleCidr('notanip')).toBe(false);
    expect(isPlausibleCidr('')).toBe(false);
  });
});

describe('isPlausibleArea', () => {
  it('accepts a non-negative integer', () => {
    expect(isPlausibleArea('0')).toBe(true);
    expect(isPlausibleArea('42')).toBe(true);
  });

  it('accepts a dotted-quad', () => {
    expect(isPlausibleArea('0.0.0.0')).toBe(true);
    expect(isPlausibleArea('10.0.0.1')).toBe(true);
  });

  it('rejects garbage', () => {
    expect(isPlausibleArea('x')).toBe(false);
    expect(isPlausibleArea('-1')).toBe(false);
  });
});
