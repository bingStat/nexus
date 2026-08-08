#!/usr/bin/env ruby
# frozen_string_literal: true

require "digest"

P = (1 << 255) - 19
L = (1 << 252) + 27_742_317_777_372_353_535_851_937_790_883_648_493

def mod_pow(base, exponent, mod)
  result = 1
  base %= mod
  while exponent.positive?
    result = (result * base) % mod if exponent.odd?
    base = (base * base) % mod
    exponent >>= 1
  end
  result
end

def inv(value)
  mod_pow(value, P - 2, P)
end

D = (-121_665 * inv(121_666)) % P
I = mod_pow(2, (P - 1) / 4, P)
BY = (4 * inv(5)) % P

def recover_x(y, sign)
  xx = ((y * y - 1) * inv(D * y * y + 1)) % P
  x = mod_pow(xx, (P + 3) / 8, P)
  x = (x * I) % P if (x * x - xx) % P != 0
  x = P - x if (x & 1) != sign
  x
end

BX = recover_x(BY, 0)
B = [BX, BY].freeze
IDENTITY = [0, 1].freeze

def point_add(point_a, point_b)
  x1, y1 = point_a
  x2, y2 = point_b
  denom_x = inv(1 + D * x1 * x2 * y1 * y2)
  denom_y = inv(1 - D * x1 * x2 * y1 * y2)
  x3 = ((x1 * y2 + x2 * y1) * denom_x) % P
  y3 = ((y1 * y2 + x1 * x2) * denom_y) % P
  [x3, y3]
end

def scalar_mult(point, scalar)
  result = IDENTITY
  addend = point
  while scalar.positive?
    result = point_add(result, addend) if scalar.odd?
    addend = point_add(addend, addend)
    scalar >>= 1
  end
  result
end

def bytes_to_int_le(bytes)
  bytes.each_byte.with_index.reduce(0) { |acc, (byte, index)| acc + (byte << (8 * index)) }
end

def int_to_bytes_le(value, length)
  Array.new(length) { |index| (value >> (8 * index)) & 0xff }.pack("C*")
end

def encode_point(point)
  x, y = point
  encoded = int_to_bytes_le(y, 32).bytes
  encoded[31] |= (x & 1) << 7
  encoded.pack("C*")
end

def decode_pem(path)
  body = File.read(path)
             .lines
             .reject { |line| line.start_with?("-----") }
             .join
             .gsub(/\s+/, "")
  base64_decode(body)
end

def base64_decode(text)
  alphabet = "ABCDEFGHIJKLMNOPQRSTUVWXYZabcdefghijklmnopqrstuvwxyz0123456789+/"
  table = alphabet.chars.each_with_index.to_h
  output = +"".b
  text.scan(/.{1,4}/).each do |chunk|
    padding = chunk.count("=")
    values = chunk.tr("=", "A").chars.map { |char| table.fetch(char) }
    number = values.reduce(0) { |acc, value| (acc << 6) | value }
    output << ((number >> 16) & 0xff)
    output << ((number >> 8) & 0xff) if padding < 2
    output << (number & 0xff) if padding < 1
  end
  output
end

def private_seed(path)
  der = decode_pem(path)
  marker = "\x04\x20".b
  index = der.index(marker)
  abort "unsupported Ed25519 private key format" unless index

  seed = der.byteslice(index + marker.bytesize, 32)
  abort "invalid Ed25519 private key seed" unless seed && seed.bytesize == 32

  seed
end

def sign_message(private_key_path, message_path, signature_path)
  seed = private_seed(private_key_path)
  message = File.binread(message_path)
  digest = Digest::SHA512.digest(seed)
  lower = digest.byteslice(0, 32).bytes
  lower[0] &= 248
  lower[31] &= 63
  lower[31] |= 64
  a = bytes_to_int_le(lower.pack("C*"))
  prefix = digest.byteslice(32, 32)
  public_key = encode_point(scalar_mult(B, a))
  r = bytes_to_int_le(Digest::SHA512.digest(prefix + message)) % L
  encoded_r = encode_point(scalar_mult(B, r))
  k = bytes_to_int_le(Digest::SHA512.digest(encoded_r + public_key + message)) % L
  s = (r + k * a) % L
  File.binwrite(signature_path, encoded_r + int_to_bytes_le(s, 32))
end

def key_id(public_key_path)
  der = decode_pem(public_key_path)
  "sha256:#{Digest::SHA256.hexdigest(der)}"
end

if $PROGRAM_NAME == __FILE__
  command, *args = ARGV
  case command
  when "sign"
    abort "usage: #{$PROGRAM_NAME} sign <private-key-pem> <message-file> <signature-file>" unless args.length == 3

    sign_message(args[0], args[1], args[2])
  when "key-id"
    abort "usage: #{$PROGRAM_NAME} key-id <public-key-pem>" unless args.length == 1

    puts key_id(args[0])
  else
    abort "usage: #{$PROGRAM_NAME} sign|key-id ..."
  end
end
