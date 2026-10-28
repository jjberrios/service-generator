package __BASE_PACKAGE__.security.service.impl;

import __BASE_PACKAGE__.security.service.JwtValidatorService;
import io.jsonwebtoken.Claims;
import io.jsonwebtoken.ExpiredJwtException;
import io.jsonwebtoken.Jws;
import io.jsonwebtoken.JwtParser;
import io.jsonwebtoken.Jwts;
import io.jsonwebtoken.MalformedJwtException;
import io.jsonwebtoken.UnsupportedJwtException;
import io.jsonwebtoken.security.Keys;
import io.jsonwebtoken.security.SignatureException;
import jakarta.annotation.PostConstruct;
import java.nio.charset.StandardCharsets;
import javax.crypto.SecretKey;
import org.slf4j.Logger;
import org.slf4j.LoggerFactory;
import org.springframework.beans.factory.annotation.Value;
import org.springframework.stereotype.Component;

@Component
public class JwtValidatorServiceImpl implements JwtValidatorService {

    private static final Logger JWT_VALIDATION_LOGGER =
            LoggerFactory.getLogger(JwtValidatorServiceImpl.class);

    @Value("${security.jwt.secret-key}")
    private String jwtSecretString;

    private JwtParser jwtParser;

    @PostConstruct
    public void init() {
        SecretKey secretKey = Keys.hmacShaKeyFor(jwtSecretString.getBytes(StandardCharsets.UTF_8));
        this.jwtParser = Jwts.parserBuilder()
                .setSigningKey(secretKey)
                .build();
    }

    @Override
    public boolean validateToken(String token) {
        try {
            jwtParser.parseClaimsJws(token);
            return true;
        } catch (SignatureException exception) {
            JWT_VALIDATION_LOGGER.error("JWT validation failed: invalid signature -> {}", exception.getMessage());
        } catch (MalformedJwtException exception) {
            JWT_VALIDATION_LOGGER.error("JWT validation failed: malformed token -> {}", exception.getMessage());
        } catch (UnsupportedJwtException exception) {
            JWT_VALIDATION_LOGGER.error("JWT validation failed: unsupported token -> {}", exception.getMessage());
        } catch (IllegalArgumentException exception) {
            JWT_VALIDATION_LOGGER.error("JWT validation failed: empty claims -> {}", exception.getMessage());
        }

        return false;
    }

    @Override
    public Claims getClaimsFromToken(String token) throws ExpiredJwtException, SignatureException {
        Jws<Claims> jwsClaims = jwtParser.parseClaimsJws(token);
        return jwsClaims.getBody();
    }
}
