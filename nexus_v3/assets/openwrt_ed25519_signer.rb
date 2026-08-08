#!/usr/bin/env ruby
# frozen_string_literal: true

require "digest"
require "securerandom"

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

def base64_encode(binary)
  [binary].pack("m0")
end

def u32(value)
  [value].pack("N")
end

def ssh_string(binary)
  u32(binary.bytesize) + binary
end

def read_u32(binary, offset)
  [binary.byteslice(offset, 4).unpack1("N"), offset + 4]
end

def read_ssh_string(binary, offset)
  length, offset = read_u32(binary, offset)
  [binary.byteslice(offset, length), offset + length]
end

def public_key_from_seed(seed)
  digest = Digest::SHA512.digest(seed)
  lower = digest.byteslice(0, 32).bytes
  lower[0] &= 248
  lower[31] &= 63
  lower[31] |= 64
  a = bytes_to_int_le(lower.pack("C*"))
  encode_point(scalar_mult(B, a))
end

def openssh_public_blob(raw_public_key)
  ssh_string("ssh-ed25519".b) + ssh_string(raw_public_key)
end

def openssh_public_line(raw_public_key, comment)
  "ssh-ed25519 #{base64_encode(openssh_public_blob(raw_public_key))} #{comment}".strip
end

def openssh_private_pem(seed, comment)
  raw_public_key = public_key_from_seed(seed)
  public_blob = openssh_public_blob(raw_public_key)
  private_key = seed + raw_public_key
  check = SecureRandom.random_number(1 << 32)
  private_blob = u32(check) + u32(check) +
                 ssh_string("ssh-ed25519".b) +
                 ssh_string(raw_public_key) +
                 ssh_string(private_key) +
                 ssh_string(comment.b)
  pad = 1
  while private_blob.bytesize % 8 != 0
    private_blob += pad.chr
    pad += 1
  end
  body = "openssh-key-v1\0".b +
         ssh_string("none".b) +
         ssh_string("none".b) +
         ssh_string("".b) +
         u32(1) +
         ssh_string(public_blob) +
         ssh_string(private_blob)
  encoded = base64_encode(body).scan(/.{1,70}/).join("\n")
  "-----BEGIN OPENSSH PRIVATE KEY-----\n#{encoded}\n-----END OPENSSH PRIVATE KEY-----\n"
end

def parse_openssh_public(path)
  parts = File.read(path).strip.split(/\s+/, 3)
  abort "unsupported OpenSSH public key" unless parts[0] == "ssh-ed25519"

  blob = base64_decode(parts[1])
  key_type, offset = read_ssh_string(blob, 0)
  abort "unsupported OpenSSH public key type" unless key_type == "ssh-ed25519"

  raw_public_key, = read_ssh_string(blob, offset)
  abort "invalid Ed25519 public key" unless raw_public_key && raw_public_key.bytesize == 32

  raw_public_key
end

def parse_openssh_private(path)
  text = File.read(path)
  body = text.lines.reject { |line| line.start_with?("-----") }.join.gsub(/\s+/, "")
  binary = base64_decode(body)
  magic = "openssh-key-v1\0".b
  abort "unsupported OpenSSH private key format" unless binary.start_with?(magic)

  offset = magic.bytesize
  cipher, offset = read_ssh_string(binary, offset)
  kdf, offset = read_ssh_string(binary, offset)
  _kdf_options, offset = read_ssh_string(binary, offset)
  abort "encrypted OpenSSH private keys are not supported" unless cipher == "none" && kdf == "none"

  nkeys, offset = read_u32(binary, offset)
  abort "invalid OpenSSH private key count" unless nkeys == 1

  _public_blob, offset = read_ssh_string(binary, offset)
  private_blob, = read_ssh_string(binary, offset)
  check1, inner = read_u32(private_blob, 0)
  check2, inner = read_u32(private_blob, inner)
  abort "OpenSSH private key check failed" unless check1 == check2

  key_type, inner = read_ssh_string(private_blob, inner)
  abort "unsupported OpenSSH private key type" unless key_type == "ssh-ed25519"

  _raw_public_key, inner = read_ssh_string(private_blob, inner)
  private_key, = read_ssh_string(private_blob, inner)
  abort "invalid OpenSSH Ed25519 private key" unless private_key && private_key.bytesize >= 64

  private_key.byteslice(0, 32)
end

def private_seed(path)
  text = File.read(path)
  return parse_openssh_private(path) if text.start_with?("-----BEGIN OPENSSH PRIVATE KEY-----")

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
  text = File.read(public_key_path)
  der = if text.start_with?("ssh-ed25519 ")
          raw_public_key = parse_openssh_public(public_key_path)
          ["302a300506032b6570032100"].pack("H*") + raw_public_key
        else
          decode_pem(public_key_path)
        end
  "sha256:#{Digest::SHA256.hexdigest(der)}"
end

def generate_key(private_key_path, public_key_path, comment)
  seed = SecureRandom.random_bytes(32)
  raw_public_key = public_key_from_seed(seed)
  File.binwrite(private_key_path, openssh_private_pem(seed, comment))
  File.write(public_key_path, "#{openssh_public_line(raw_public_key, comment)}\n")
  File.chmod(0o600, private_key_path)
  File.chmod(0o644, public_key_path)
end

def derive_public(private_key_path, public_key_path, comment)
  seed = private_seed(private_key_path)
  raw_public_key = public_key_from_seed(seed)
  File.write(public_key_path, "#{openssh_public_line(raw_public_key, comment)}\n")
  File.chmod(0o644, public_key_path)
end

if $PROGRAM_NAME == __FILE__
  command, *args = ARGV
  case command
  when "generate"
    abort "usage: #{$PROGRAM_NAME} generate <private-key> <public-key> <comment>" unless args.length == 3

    generate_key(args[0], args[1], args[2])
  when "public"
    abort "usage: #{$PROGRAM_NAME} public <private-key> <public-key> <comment>" unless args.length == 3

    derive_public(args[0], args[1], args[2])
  when "sign"
    abort "usage: #{$PROGRAM_NAME} sign <private-key> <message-file> <signature-file>" unless args.length == 3

    sign_message(args[0], args[1], args[2])
  when "key-id"
    abort "usage: #{$PROGRAM_NAME} key-id <public-key>" unless args.length == 1

    puts key_id(args[0])
  else
    abort "usage: #{$PROGRAM_NAME} generate|public|sign|key-id ..."
  end
end
