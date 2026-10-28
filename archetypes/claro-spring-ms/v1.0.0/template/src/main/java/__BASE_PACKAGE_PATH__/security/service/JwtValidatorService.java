package __BASE_PACKAGE__.security.service;

import io.jsonwebtoken.Claims;
import io.jsonwebtoken.ExpiredJwtException;
import io.jsonwebtoken.security.SignatureException;

public interface JwtValidatorService {

    boolean validateToken(String token);

    Claims getClaimsFromToken(String token) throws ExpiredJwtException, SignatureException;
}
